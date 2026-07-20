"""B4 — fleet dashboard: telemetry aggregation, version drift, per-town status."""

from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator import audit
from orchestrator.app_client import client_for_tenant
from orchestrator.db import get_db
from orchestrator.models import TelemetrySnapshot, Tenant, TenantStatus
from orchestrator.provisioner import get_platform_secret
from orchestrator.queries import latest_release, latest_snapshots
from orchestrator.security import require_operator, require_panel_token
from orchestrator.telemetry import sanitize_telemetry

router = APIRouter(prefix="/api/fleet", tags=["fleet"])


def _operational_only(payload: dict | None) -> dict | None:
    """Drop resident-derived 311 analytics from a per-town telemetry payload —
    those are only ever exposed as region aggregates, never town-by-town."""
    if not payload:
        return payload
    return {k: v for k, v in payload.items() if k not in ("request_stats",)}


def poll_all_telemetry(db: Session, actor: str = "auto-poller") -> dict:
    """Poll every active town's A5 telemetry endpoint; store sanitized snapshots
    and re-evaluate alerts. Shared by the manual /refresh endpoint and the
    background auto-poll loop so status stays current without a manual click."""
    tenants = db.execute(
        select(Tenant).where(Tenant.status == TenantStatus.ACTIVE)
    ).scalars().all()
    polled, reachable = 0, 0
    for tenant in tenants:
        client = client_for_tenant(
            tenant, panel_token=get_platform_secret(db, tenant.id, "PROVISIONING_TOKEN")
        )
        try:
            raw = client.telemetry()
            payload = sanitize_telemetry(raw)
            snap = TelemetrySnapshot(
                tenant_id=tenant.id,
                reachable=True,
                version=payload.get("version"),
                payload=payload,
            )
            if payload.get("version"):
                tenant.running_version = payload["version"]
            reachable += 1
        except Exception as exc:  # noqa: BLE001 — an unreachable town is data, not an error
            snap = TelemetrySnapshot(
                tenant_id=tenant.id, reachable=False, payload={"error": str(exc)[:500]}
            )
        finally:
            client.close()
        db.add(snap)
        polled += 1
    audit.record(db, actor, "fleet.telemetry_refreshed", None, polled=polled, reachable=reachable)
    db.commit()
    # Fresh telemetry → re-evaluate alert conditions (down, drift, …).
    from orchestrator import insights

    new_alerts = len(insights.evaluate_alerts(db))
    return {"polled": polled, "reachable": reachable, "new_alerts": new_alerts}


@router.post("/refresh")
def refresh_telemetry(
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    """Poll every active town's A5 telemetry endpoint; store sanitized snapshots."""
    return poll_all_telemetry(db, actor)


@router.get("/summary")
def fleet_summary(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    tenants = db.execute(select(Tenant)).scalars().all()
    latest = latest_release(db)
    snapshots = latest_snapshots(db)

    status_counts = Counter(t.status for t in tenants)
    version_counts = Counter(t.running_version or "unknown" for t in tenants
                             if t.status == TenantStatus.ACTIVE)

    towns = []
    for t in tenants:
        snap = snapshots.get(t.id)
        towns.append(
            {
                "id": t.id,
                "slug": t.slug,
                "name": t.name,
                "host": t.external_host,
                "status": t.status,
                "running_version": t.running_version,
                "target_version": t.target_version,
                "drift": bool(
                    latest
                    and t.status == TenantStatus.ACTIVE
                    and t.running_version != latest.version
                ),
                "reachable": snap.reachable if snap else None,
                "last_seen": snap.collected_at.isoformat() if snap else None,
                # Operational telemetry only — never surface a town's 311/resident
                # analytics per-town (request_stats). Those are region-only.
                "telemetry": _operational_only(snap.payload) if snap else None,
            }
        )

    return {
        "tenants_total": len(tenants),
        "status_counts": dict(status_counts),
        "version_counts": dict(version_counts),
        "latest_release": latest.version if latest else None,
        "drifted": sum(1 for t in towns if t["drift"]),
        "towns": towns,
    }


@router.get("/drift")
def fleet_drift(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    latest = latest_release(db)
    if not latest:
        return {"latest_release": None, "drifted_towns": []}
    tenants = db.execute(
        select(Tenant).where(Tenant.status == TenantStatus.ACTIVE)
    ).scalars().all()
    drifted = [
        {"slug": t.slug, "running_version": t.running_version, "target_version": t.target_version}
        for t in tenants
        if t.running_version != latest.version
    ]
    return {"latest_release": latest.version, "drifted_towns": drifted}
