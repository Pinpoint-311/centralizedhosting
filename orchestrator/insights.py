"""Fleet insights: cost/chargeback rollup, uptime/SLA, and alert evaluation.

All derived from the PII-safe telemetry snapshots the panel already collects —
nothing here touches resident data.
"""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.key_catalog import (
    STATE_SHARED,
    normalize_assignments,
    owner_is_state,
    service_for_key,
)
from orchestrator.models import Alert, Release, TelemetrySnapshot, Tenant, TenantStatus, utcnow

# Fallback per-unit cost estimates (USD) when a town's telemetry doesn't carry
# an explicit cost. Deployments can tune these; they only affect the rollup.
UNIT_COST = {
    "tokens_input": 0.000000125,
    "tokens_output": 0.000000375,
    "characters": 0.00002,   # ~$20 / M chars (translation)
    "calls": 0.005,          # geocode/static map per-call
}

# Which assignable service each telemetry usage bucket rolls up under, so cost
# can be attributed to state vs. town via the key-responsibility matrix.
SERVICE_BY_USAGE = {
    "vertex_ai": "ai",
    "ai": "ai",
    "translation": "translation",
    "maps_geocode": "maps",
    "maps_static": "maps",
    "maps": "maps",
}


def _latest_snapshots(db: Session) -> dict[str, TelemetrySnapshot]:
    latest: dict[str, TelemetrySnapshot] = {}
    for snap in db.execute(
        select(TelemetrySnapshot).order_by(TelemetrySnapshot.collected_at)
    ).scalars():
        latest[snap.tenant_id] = snap
    return latest


def _usage_cost(usage: dict) -> float:
    """Estimate a service's cost from its usage counters, honoring an explicit
    `cost` field when the town reports one."""
    if isinstance(usage, dict) and "cost" in usage:
        try:
            return float(usage["cost"])
        except (TypeError, ValueError):
            pass
    total = 0.0
    if isinstance(usage, dict):
        for metric, unit in UNIT_COST.items():
            total += float(usage.get(metric, 0) or 0) * unit
    return round(total, 4)


def cost_summary(db: Session) -> dict:
    """Per-town and fleet cost, split into state-borne vs town-borne using each
    town's key-responsibility matrix. Powers the chargeback view."""
    tenants = db.execute(select(Tenant)).scalars().all()
    snaps = _latest_snapshots(db)

    towns = []
    fleet_state = fleet_town = 0.0
    service_totals: dict[str, float] = defaultdict(float)

    for t in tenants:
        snap = snaps.get(t.id)
        api_usage = (snap.payload.get("api_usage") if snap and snap.payload else None) or {}
        assignments = normalize_assignments(t.key_assignments)
        town_state = town_town = 0.0
        services = []
        for bucket, usage in api_usage.items():
            cost = _usage_cost(usage)
            svc = SERVICE_BY_USAGE.get(bucket, bucket)
            owner = assignments.get(svc, "town")
            borne = "state" if owner_is_state(owner) else "town"
            if borne == "state":
                town_state += cost
            else:
                town_town += cost
            service_totals[svc] += cost
            services.append({"service": svc, "bucket": bucket, "cost": cost, "borne_by": borne})
        fleet_state += town_state
        fleet_town += town_town
        towns.append(
            {
                "id": t.id,
                "slug": t.slug,
                "name": t.name,
                "state_borne": round(town_state, 4),
                "town_borne": round(town_town, 4),
                "total": round(town_state + town_town, 4),
                "services": services,
            }
        )

    towns.sort(key=lambda x: x["total"], reverse=True)
    return {
        "fleet_total": round(fleet_state + fleet_town, 4),
        "state_borne": round(fleet_state, 4),
        "town_borne": round(fleet_town, 4),
        "by_service": {k: round(v, 4) for k, v in sorted(service_totals.items())},
        "towns": towns,
        "note": "Estimated from latest telemetry; explicit per-service cost fields override the estimate.",
    }


def sla_summary(db: Session, days: int = 30) -> dict:
    """Uptime % and incident count per town from telemetry reachability."""
    since = utcnow() - timedelta(days=days)
    rows = db.execute(
        select(TelemetrySnapshot)
        .where(TelemetrySnapshot.collected_at >= since)
        .order_by(TelemetrySnapshot.collected_at)
    ).scalars().all()

    by_tenant: dict[str, list[TelemetrySnapshot]] = defaultdict(list)
    for r in rows:
        by_tenant[r.tenant_id].append(r)

    slug = {t.id: t.slug for t in db.execute(select(Tenant)).scalars()}
    name = {t.id: t.name for t in db.execute(select(Tenant)).scalars()}

    towns = []
    for tid, snaps in by_tenant.items():
        checks = len(snaps)
        up = sum(1 for s in snaps if s.reachable)
        # incidents = transitions into an unreachable run
        incidents = 0
        prev_ok = True
        for s in snaps:
            if not s.reachable and prev_ok:
                incidents += 1
            prev_ok = s.reachable
        towns.append(
            {
                "id": tid,
                "slug": slug.get(tid),
                "name": name.get(tid),
                "checks": checks,
                "reachable": up,
                "uptime_percent": round(up / checks * 100, 3) if checks else None,
                "incidents": incidents,
            }
        )
    towns.sort(key=lambda x: (x["uptime_percent"] is None, x["uptime_percent"] or 0))
    return {"period_days": days, "towns": towns}


def evaluate_alerts(db: Session) -> list[Alert]:
    """Check the fleet against alert conditions and open new alerts (deduped
    against existing open alerts of the same tenant+kind). Returns new alerts."""
    tenants = db.execute(
        select(Tenant).where(Tenant.status == TenantStatus.ACTIVE)
    ).scalars().all()
    latest_release = db.execute(
        select(Release).order_by(Release.published_at.desc())
    ).scalars().first()
    snaps = _latest_snapshots(db)

    open_alerts = db.execute(
        select(Alert).where(Alert.acknowledged_at.is_(None))
    ).scalars().all()
    open_keys = {(a.tenant_id, a.kind) for a in open_alerts}

    new: list[Alert] = []

    def raise_alert(t, kind, severity, message):
        if (t.id, kind) in open_keys:
            return
        a = Alert(tenant_id=t.id, tenant_slug=t.slug, kind=kind,
                  severity=severity, message=message)
        db.add(a)
        new.append(a)
        open_keys.add((t.id, kind))

    for t in tenants:
        snap = snaps.get(t.id)
        if snap is not None and snap.reachable is False:
            raise_alert(t, "down", "critical", f"{t.name} is not reachable.")
        if latest_release and t.running_version and t.running_version != latest_release.version:
            raise_alert(
                t, "drift", "warning",
                f"{t.name} runs {t.running_version}; latest is {latest_release.version}.",
            )

    if new:
        db.commit()
        _notify(new)
    return new


def _notify(alerts: list[Alert]) -> None:
    """Best-effort webhook notification (Slack-compatible JSON)."""
    from orchestrator.config import settings

    url = getattr(settings, "alert_webhook_url", "")
    if not url:
        return
    import httpx

    text = "🚨 Pinpoint 311 fleet alerts:\n" + "\n".join(
        f"• [{a.severity}] {a.message}" for a in alerts
    )
    try:
        httpx.post(url, json={"text": text}, timeout=5.0)
    except Exception:
        pass  # never let notification failure break evaluation
