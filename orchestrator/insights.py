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
from orchestrator.models import Alert, TelemetrySnapshot, Tenant, TenantStatus, utcnow
from orchestrator.queries import latest_release, latest_snapshots

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
    snaps = latest_snapshots(db)

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
    latest = latest_release(db)
    snaps = latest_snapshots(db)

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

    from orchestrator.config import settings

    for t in tenants:
        snap = snaps.get(t.id)
        if snap is not None and snap.reachable is False:
            raise_alert(t, "down", "critical", f"{t.name} is not reachable.")
        if latest and t.running_version and t.running_version != latest.version:
            raise_alert(
                t, "drift", "warning",
                f"{t.name} runs {t.running_version}; latest is {latest.version}.",
            )
        # Degraded integrations (reachable, but a dependency the town reports as
        # unhealthy in its telemetry) — operational, never resident data.
        for name in _unhealthy_integrations(snap):
            raise_alert(
                t, "health", "warning",
                f"{t.name}: integration '{name}' is reporting unhealthy.",
            )

    # TLS certificate expiry — probe each active town's public host.
    if settings.ssl_check_enabled:
        from orchestrator import sslcheck

        warn = settings.cert_expiry_warn_days
        for t in tenants:
            days = sslcheck.days_until_expiry(t.external_host)
            if days is None or days > warn:
                continue
            severity = "critical" if days <= max(0, warn // 3) else "warning"
            when = "has expired" if days < 0 else f"expires in {days} day(s)"
            raise_alert(t, "cert_expiry", severity, f"{t.name}: TLS certificate {when}.")

    if new:
        db.commit()
        _notify(new)
    return new


def _unhealthy_integrations(snap) -> list[str]:
    """Names of integrations a town reports as not-ok in its telemetry.
    Accepts either {name: bool} or {name: {"status"|"ok": ...}} shapes."""
    health = (snap.payload.get("integration_health") if snap and snap.payload else None) or {}
    if not isinstance(health, dict):
        return []
    bad = []
    for name, value in health.items():
        if isinstance(value, dict):
            ok = value.get("ok")
            status = str(value.get("status", "")).lower()
            healthy = ok is True or status in ("ok", "healthy", "up", "pass")
            if ok is None and not status:
                healthy = True  # no signal -> don't alert
        else:
            healthy = bool(value) if isinstance(value, bool) else str(value).lower() in (
                "ok", "healthy", "up", "true", "pass"
            )
        if not healthy:
            bad.append(str(name))
    return bad


def _canonical_for(db: Session, tenant_id: str) -> dict[str, str]:
    from orchestrator.models import CategoryMapping

    return {
        m.local_key.lower(): m.canonical_code
        for m in db.execute(
            select(CategoryMapping).where(CategoryMapping.tenant_id == tenant_id)
        ).scalars()
    }


def _town_stats(snap) -> dict:
    rs = (snap.payload.get("request_stats") if snap and snap.payload else None) or {}
    return {
        "total": int(rs.get("total", 0) or 0),
        "open": int(rs.get("open", 0) or 0),
        "closed": int(rs.get("closed", 0) or 0),
        "avg_close_hours": rs.get("avg_close_hours"),
        "by_category": rs.get("by_category", {}) or {},
    }


def analytics(db: Session, min_cell: int | None = None, region_label: str = "region") -> dict:
    """311 / resident-derived analytics — REGION-LEVEL ONLY, for everyone.

    Deliberately never returns a single town's 311 figures. Per-town aggregate
    counts are used only as an internal input to compute region rollups; the
    output exposes region + program-wide aggregates. Regions with fewer than
    `min_cell` contributing towns are folded into a combined "Other regions"
    bucket (still counted program-wide) so no region maps to one town. This is
    the impenetrable-wall guarantee: the state sees county-by-county, a town
    sees only its own instance (never through the panel), and no town's numbers
    are ever attributable to it here.
    """
    from orchestrator.config import settings

    min_cell = settings.analytics_min_cell if min_cell is None else min_cell
    tenants = db.execute(select(Tenant)).scalars().all()
    snaps = latest_snapshots(db)

    by_category: dict[str, int] = defaultdict(int)
    region_acc: dict[str, dict] = defaultdict(lambda: {"total": 0, "closed": 0, "towns": 0})
    program_total = 0
    unmapped = 0

    for t in tenants:
        stats = _town_stats(snaps.get(t.id))
        mapping = _canonical_for(db, t.id)
        for local, count in stats["by_category"].items():
            key = str(local).lower()
            code = mapping.get(key, "other")
            if code == "other" and key not in mapping:
                unmapped += int(count or 0)
            by_category[code] += int(count or 0)
        program_total += stats["total"]
        region = t.county or "Unassigned"
        region_acc[region]["total"] += stats["total"]
        region_acc[region]["closed"] += stats["closed"]
        region_acc[region]["towns"] += 1

    # Fold sub-threshold regions into a combined bucket so none maps to one town.
    combined = {"total": 0, "closed": 0, "towns": 0}
    regions = []
    for region, agg in region_acc.items():
        if agg["towns"] < min_cell:
            combined["total"] += agg["total"]
            combined["closed"] += agg["closed"]
            combined["towns"] += agg["towns"]
            continue
        rate = round(agg["closed"] / agg["total"] * 100, 1) if agg["total"] else None
        regions.append({
            f"{region_label}": region, "towns": agg["towns"],
            "total_requests": agg["total"], "close_rate_percent": rate,
        })
    if combined["towns"] >= min_cell:
        rate = round(combined["closed"] / combined["total"] * 100, 1) if combined["total"] else None
        regions.append({
            f"{region_label}": "Other (small regions combined)", "towns": combined["towns"],
            "total_requests": combined["total"], "close_rate_percent": rate,
        })
        hidden_towns = 0
    else:
        hidden_towns = combined["towns"]  # too few even combined -> not shown at all

    regions.sort(key=lambda r: -r["total_requests"])
    return {
        "program_total_requests": program_total,
        "by_canonical_category": dict(sorted(by_category.items(), key=lambda kv: -kv[1])),
        "regions": regions,
        "unmapped_requests": unmapped,
        "min_cell": min_cell,
        "towns_withheld_for_privacy": hidden_towns,
        "note": (
            "Region-level only. Individual municipalities are never shown; regions "
            "with too few towns are combined or withheld to prevent identification."
        ),
    }


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
