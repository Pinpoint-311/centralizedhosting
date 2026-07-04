"""B4 — fleet dashboard: telemetry aggregation, version drift, per-town status."""

from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator import audit
from orchestrator.app_client import client_for_tenant
from orchestrator.db import get_db
from orchestrator.models import Release, TelemetrySnapshot, Tenant, TenantStatus
from orchestrator.provisioner import get_platform_secret
from orchestrator.security import require_panel_token
from orchestrator.telemetry import sanitize_telemetry

router = APIRouter(prefix="/api/fleet", tags=["fleet"])


def _latest_snapshots(db: Session) -> dict[str, TelemetrySnapshot]:
    latest: dict[str, TelemetrySnapshot] = {}
    for snap in db.execute(
        select(TelemetrySnapshot).order_by(TelemetrySnapshot.collected_at)
    ).scalars():
        latest[snap.tenant_id] = snap
    return latest


@router.post("/refresh")
def refresh_telemetry(
    db: Session = Depends(get_db),
    actor: str = Depends(require_panel_token),
):
    """Poll every active town's A5 telemetry endpoint; store sanitized snapshots."""
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
    return {"polled": polled, "reachable": reachable}


@router.get("/summary")
def fleet_summary(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    tenants = db.execute(select(Tenant)).scalars().all()
    latest_release = db.execute(
        select(Release).order_by(Release.published_at.desc())
    ).scalars().first()
    snapshots = _latest_snapshots(db)

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
                    latest_release
                    and t.status == TenantStatus.ACTIVE
                    and t.running_version != latest_release.version
                ),
                "reachable": snap.reachable if snap else None,
                "last_seen": snap.collected_at.isoformat() if snap else None,
                "telemetry": snap.payload if snap else None,
            }
        )

    return {
        "tenants_total": len(tenants),
        "status_counts": dict(status_counts),
        "version_counts": dict(version_counts),
        "latest_release": latest_release.version if latest_release else None,
        "drifted": sum(1 for t in towns if t["drift"]),
        "towns": towns,
    }


@router.get("/drift")
def fleet_drift(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    latest_release = db.execute(
        select(Release).order_by(Release.published_at.desc())
    ).scalars().first()
    if not latest_release:
        return {"latest_release": None, "drifted_towns": []}
    tenants = db.execute(
        select(Tenant).where(Tenant.status == TenantStatus.ACTIVE)
    ).scalars().all()
    drifted = [
        {"slug": t.slug, "running_version": t.running_version, "target_version": t.target_version}
        for t in tenants
        if t.running_version != latest_release.version
    ]
    return {"latest_release": latest_release.version, "drifted_towns": drifted}
