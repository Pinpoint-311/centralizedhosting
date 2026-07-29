"""Hosting-provider admin — the entity running this control plane (a state,
county, city, university, or agency), NOT a hosted municipality.

Mirrors the Pinpoint 311 app's admin console, grouped the same way:
  Branding & Setup   → platform branding + organization identity
  System & Compliance → effective system settings + system health

Municipality management (tenants) and fleet management (insights/operations)
live elsewhere; this is the provider's own setup.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orchestrator import __version__, audit
from orchestrator.config import settings
from orchestrator.db import get_db
from orchestrator.models import AuditLog, FederationConfig, PlatformConfig, Tenant, TenantStatus
from orchestrator.security import require_admin, require_operator, require_panel_token, resolve_role

router = APIRouter(prefix="/api", tags=["platform-admin"])

DEFAULT_NAME = "Pinpoint 311"
DEFAULT_TAGLINE = "Hosting Control Plane"
ORG_TYPES = {"state", "county", "city", "university", "agency", "other"}


def get_config(db: Session) -> PlatformConfig | None:
    return db.get(PlatformConfig, "default")


def branding_from(cfg: PlatformConfig | None) -> dict:
    return {
        "platform_name": (cfg.platform_name if cfg else None) or DEFAULT_NAME,
        "tagline": (cfg.tagline if cfg else None) or DEFAULT_TAGLINE,
        "logo_url": cfg.logo_url if cfg else None,
        "primary_color": cfg.primary_color if cfg else None,
        "support_email": cfg.support_email if cfg else None,
    }


def branding(db: Session) -> dict:
    """Non-sensitive branding for the panel shell + login (no auth needed)."""
    return branding_from(get_config(db))


def _out(cfg: PlatformConfig | None) -> dict:
    return {
        **branding_from(cfg),
        "org_legal_name": cfg.org_legal_name if cfg else None,
        "org_type": (cfg.org_type if cfg else None) or "agency",
        "jurisdiction": cfg.jurisdiction if cfg else None,
        "contact_name": cfg.contact_name if cfg else None,
        "contact_email": cfg.contact_email if cfg else None,
        "contact_phone": cfg.contact_phone if cfg else None,
        "address": cfg.address if cfg else None,
        "website": cfg.website if cfg else None,
    }


@router.get("/platform/config")
def get_platform_config(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    return _out(get_config(db))


class PlatformUpdate(BaseModel):
    platform_name: str | None = Field(default=None, max_length=120)
    tagline: str | None = Field(default=None, max_length=160)
    logo_url: str | None = None
    primary_color: str | None = Field(default=None, max_length=9)
    support_email: str | None = None
    org_legal_name: str | None = None
    org_type: str | None = None
    jurisdiction: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    address: str | None = None
    website: str | None = None


@router.put("/platform/config")
def put_platform_config(body: PlatformUpdate, db: Session = Depends(get_db),
                        actor: str = Depends(require_admin)):
    cfg = get_config(db)
    created = cfg is None
    if created:
        cfg = PlatformConfig(id="default")
    # Partial update — Branding and Organization edit the same row, so only the
    # fields a page actually sends are touched (the rest are left intact).
    data = body.model_dump(exclude_unset=True)
    if "org_type" in data:
        val = data.pop("org_type")  # always remove so the loop below can't re-set it
        cfg.org_type = val if val in ORG_TYPES else "other"
    for k, v in data.items():
        setattr(cfg, k, (v.strip() or None) if isinstance(v, str) else v)
    cfg.updated_by = actor
    if created:
        db.add(cfg)
    audit.record(db, actor, "platform.config_updated", None, fields=sorted(data.keys()))
    db.commit()
    return _out(cfg)


# ---- System & Compliance ----------------------------------------------------

def _posture_control(key: str, label: str, enabled: bool, severity: str,
                     on_detail: str, off_impact: str) -> dict:
    """One hardening control: whether it's on, and — when it isn't — what that
    actually means. A flat on/off dump can't tell an operator that
    ``cosign_verify: off`` is a finding while ``base_domain`` is just a fact."""
    return {
        "key": key,
        "label": label,
        "enabled": enabled,
        # Severity describes the gap when the control is OFF; ignored when on.
        "severity": "ok" if enabled else severity,
        "detail": on_detail if enabled else off_impact,
    }


@router.get("/system/config")
def system_config(_: str = Depends(require_operator)):
    """Deployment identity + security posture (read-only; env-driven).

    Deliberately does NOT repeat the KMS backend or the background-loop
    intervals — System Health owns those, and showing them twice invites the
    two views to disagree.
    """
    import os as _os

    from orchestrator import encryption

    s = settings
    require_kms = encryption._kms_required()
    posture = [
        _posture_control(
            "require_kms", "Require cloud KMS", require_kms, "warning",
            "Secret encryption must wrap the data key with a real cloud KMS.",
            "Secret encryption may fall back to the local panel key if the KMS is unreachable. "
            "Set REQUIRE_KMS to fail closed instead.",
        ),
        _posture_control(
            "require_signed_images", "Require signed images", s.require_signed_images, "warning",
            "Only images with a valid signature are deployed to towns.",
            "Unsigned container images can be deployed to town instances.",
        ),
        _posture_control(
            "cosign_verify", "Verify image signatures", s.cosign_verify, "warning",
            "Image signatures are checked with cosign before a rollout.",
            "Image signatures are not actually verified before a rollout, so a signature "
            "requirement can't be enforced.",
        ),
        _posture_control(
            "waf_enabled", "Web application firewall", s.waf_enabled, "warning",
            "Caddy applies the WAF ruleset in front of town instances.",
            "No WAF ruleset is applied in front of town instances.",
        ),
        _posture_control(
            "rate_limit", "API rate limiting", s.rate_limit_rpm > 0, "warning",
            f"Requests are capped at {s.rate_limit_rpm}/min per client."
            + ("" if _os.getenv("REDIS_URL", "").strip() else
               " Counters are per-process — set REDIS_URL before running multiple workers."),
            "The panel API accepts unlimited request rates from a single client.",
        ),
        _posture_control(
            "backups_enabled", "Backups", s.backups_enabled, "warning",
            f"Encrypted backups run automatically, kept {s.backup_retention_days} days.",
            "No automatic backups — the fleet registry could not be restored after a loss.",
        ),
        _posture_control(
            "apply_stacks", "Apply stacks", s.apply_stacks, "warning",
            "Provisioning deploys town stacks for real.",
            "Dry run — provisioning renders compose files but never starts anything, so "
            "towns appear provisioned while nothing is actually running. Set APPLY_STACKS "
            "when you are ready to deploy.",
        ),
        _posture_control(
            "ssl_check_enabled", "Certificate expiry monitoring", s.ssl_check_enabled, "info",
            "Town TLS certificates are probed and alert before they expire.",
            "Certificate expiry isn't monitored, so an expired town certificate surfaces "
            "as an outage rather than a warning.",
        ),
    ]
    return {
        "deployment": {
            "base_domain": s.base_domain,
            "apply_stacks": s.apply_stacks,
            "backend_image": s.backend_image,
            "frontend_image": s.frontend_image,
            "public_requests_enabled": s.public_requests_enabled,
            "telemetry_retention_days": s.telemetry_retention_days,
        },
        "posture": posture,
        "summary": {
            "enabled": sum(1 for c in posture if c["enabled"]),
            "total": len(posture),
            "warnings": sum(1 for c in posture if c["severity"] == "warning"),
        },
    }


@router.get("/system/proactive")
def system_proactive(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    """Leading-indicator health for admins: per-check status, values, and the
    suggested action. Ported from the app's /health/proactive."""
    from orchestrator import proactive_health

    return proactive_health.evaluate(db)


# ---------------------------------------------------------------- retention
# Ported from the app's /system/retention/* endpoints. In the app these set a
# town's own policy; here they set the *state's* default, which seeds the
# managed policy pushed to every hosted town.

@router.get("/system/retention/states")
def get_retention_states(_: str = Depends(require_operator)):
    """Get all supported states with their retention policies."""
    from orchestrator.retention_policy import get_all_states

    return get_all_states()


@router.get("/system/retention/policy")
def get_current_retention_policy(db: Session = Depends(get_db),
                                 _: str = Depends(require_operator)):
    """Get current retention policy configuration."""
    from orchestrator.retention_policy import get_retention_policy

    cfg = get_config(db)
    state_code = cfg.retention_state_code if cfg else "NJ"
    override_days = cfg.retention_days_override if cfg else None
    mode = cfg.retention_mode if cfg else "anonymize"

    policy = get_retention_policy(state_code)
    towns = db.execute(select(func.count()).select_from(Tenant)).scalar_one()
    return {
        "state_code": state_code,
        "policy": policy,
        "override_days": override_days,
        "effective_days": override_days if override_days else policy["retention_days"],
        "mode": mode,
        # The app reports how many of its records the policy covers; the control
        # plane's equivalent scope is the towns the policy is pushed to.
        "stats": {"towns_covered": towns},
    }


class RetentionPolicyUpdate(BaseModel):
    state_code: str | None = None
    override_days: int | None = None
    mode: str | None = None


@router.post("/system/retention/policy")
def update_retention_policy(body: RetentionPolicyUpdate, db: Session = Depends(get_db),
                            actor: str = Depends(require_admin)):
    """Update retention policy configuration (admin only)."""
    from orchestrator.retention_policy import get_retention_policy

    cfg = get_config(db) or PlatformConfig(id="default")
    if cfg not in db:
        db.add(cfg)

    if body.state_code:
        # Validate state code.
        #
        # NOTE: the app writes this as
        #     policy = get_retention_policy(state_code)
        #     if policy["state_code"] == "DEFAULT" and state_code != "DEFAULT": 400
        # which never fires — get_retention_policy echoes the *input* code back,
        # so policy["state_code"] is the typo itself, never "DEFAULT". A
        # mistyped state is silently accepted there and quietly falls back to
        # the DEFAULT 7-year policy. Checking the table directly is the same
        # intent, actually enforced.
        from orchestrator.retention_policy import STATE_RETENTION_POLICIES

        code = body.state_code.upper()
        if code not in STATE_RETENTION_POLICIES:
            raise HTTPException(400, f"Unknown state code: {body.state_code}")
        cfg.retention_state_code = code

    if body.override_days is not None:
        # 0 is the explicit "clear the override, revert to the state default"
        # signal — without this, an override once set could never be removed.
        if body.override_days == 0:
            cfg.retention_days_override = None
        elif body.override_days < 365:
            raise HTTPException(400, "Override must be at least 365 days (1 year)")
        else:
            cfg.retention_days_override = body.override_days

    if body.mode:
        if body.mode not in ["anonymize", "delete"]:
            raise HTTPException(400, "Mode must be 'anonymize' or 'delete'")
        cfg.retention_mode = body.mode

    cfg.updated_by = actor
    audit.record(db, actor, "retention.policy_updated", cfg.retention_state_code,
                 override_days=cfg.retention_days_override, mode=cfg.retention_mode)
    db.commit()
    db.refresh(cfg)
    return {
        "status": "updated",
        "state_code": cfg.retention_state_code,
        "override_days": cfg.retention_days_override,
        "mode": cfg.retention_mode,
    }


# ---------------------------------------------------------------- uptime
# Ported from the app's health API (/uptime/history, /uptime/stats,
# /uptime/check-now) — same records, same aggregation, same response shapes.

def _control_plane_checks(db: Session) -> list[tuple[str, callable]]:
    """The services this control plane owns, in the app's (name, fn) form.
    Each returns the app's {status, message} check dict."""
    from orchestrator import audit as audit_mod
    from orchestrator.encryption import _kms_provider

    def check_database(_db: Session) -> dict:
        _db.execute(select(1))
        return {"status": "healthy", "message": "Database connection successful"}

    def check_secret_encryption(_db: Session) -> dict:
        from orchestrator import security

        probe = security.decrypt_value(security.encrypt_value("healthcheck"))
        if probe != "healthcheck":
            return {"status": "down", "message": "Encrypt/decrypt round trip did not match"}
        return {"status": "healthy", "message": f"Envelope encryption via {_kms_provider()}"}

    def check_audit_chain(_db: Session) -> dict:
        chain = audit_mod.verify_chain(_db)
        if chain.get("ok"):
            return {"status": "healthy", "message": f"{chain.get('entries', 0)} entries chained and intact"}
        return {"status": "down", "message": f"Chain broken at #{chain.get('broken_at_seq')}"}

    return [
        ("database", check_database),
        ("secret_encryption", check_secret_encryption),
        ("audit_chain", check_audit_chain),
    ]


def record_uptime_check(db: Session, service_name: str, status: str,
                        response_time_ms: int | None = None,
                        error_message: str | None = None) -> None:
    """Record a health check result for a service. Called internally after
    health checks. Ported from the app's record_uptime_check."""
    from orchestrator.models import UptimeRecord

    db.add(UptimeRecord(
        service_name=service_name,
        status=status,
        response_time_ms=response_time_ms,
        error_message=error_message[:500] if error_message else None,
    ))
    db.commit()


@router.get("/system/uptime/history")
def get_uptime_history(hours: int = 24, db: Session = Depends(get_db),
                       _: str = Depends(require_panel_token)):
    """Uptime history for all services over the specified time period."""
    from datetime import timedelta

    from orchestrator.models import UptimeRecord, utcnow

    hours = min(hours, 168)  # Cap at 7 days
    since = utcnow() - timedelta(hours=hours)
    records = db.execute(
        select(UptimeRecord).where(UptimeRecord.checked_at >= since)
        .order_by(UptimeRecord.checked_at.desc())
    ).scalars().all()

    history: dict[str, list] = {}
    for record in records:
        history.setdefault(record.service_name, []).append({
            "status": record.status,
            "response_time_ms": record.response_time_ms,
            "error": record.error_message,
            "checked_at": record.checked_at.isoformat() if record.checked_at else None,
        })
    return {"period_hours": hours, "since": since.isoformat(), "services": history}


@router.get("/system/uptime/stats")
def get_uptime_stats(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    """Aggregated uptime statistics (24h, 7d, 30d percentages)."""
    from datetime import timedelta

    from sqlalchemy import Integer, case
    from sqlalchemy import func as sql_func

    from orchestrator.models import UptimeRecord, utcnow

    stats: dict[str, dict] = {}
    periods = {"24h": 24, "7d": 168, "30d": 720}
    for period_name, hours in periods.items():
        since = utcnow() - timedelta(hours=hours)
        rows = db.execute(
            select(
                UptimeRecord.service_name,
                sql_func.count(UptimeRecord.id).label("total"),
                sql_func.sum(case((UptimeRecord.status == "healthy", 1), else_=0).cast(Integer))
                .label("healthy_count"),
            ).where(UptimeRecord.checked_at >= since).group_by(UptimeRecord.service_name)
        ).all()
        for service_name, total, healthy_count in rows:
            uptime_pct = (healthy_count / total * 100) if total > 0 else 0
            stats.setdefault(service_name, {})[period_name] = {
                "uptime_percent": round(uptime_pct, 2),
                "checks": total,
                "healthy": healthy_count or 0,
            }
    return {"services": stats}


@router.post("/system/uptime/check-now")
def trigger_uptime_check(db: Session = Depends(get_db), _: str = Depends(require_admin)):
    """Manually trigger an uptime check for all services and record results."""
    import time

    results = {}
    for service_name, check_func in _control_plane_checks(db):
        start = time.time()
        try:
            check_result = check_func(db)
            response_time = int((time.time() - start) * 1000)
            status = "healthy" if check_result["status"] in ("healthy", "configured", "fallback") else "down"
            error = None if status == "healthy" else check_result.get("message")
        except Exception as e:  # noqa: BLE001
            response_time = int((time.time() - start) * 1000)
            status = "down"
            error = str(e)
        record_uptime_check(db, service_name, status, response_time, error)
        results[service_name] = {"status": status, "response_time_ms": response_time}
    return {"checked": len(results), "results": results}


@router.get("/system/health")
def system_health(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    from orchestrator import encryption

    try:
        db.execute(select(func.count(Tenant.id)))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    chain = audit.verify_chain(db)
    total = db.execute(select(func.count(Tenant.id))).scalar_one()
    active = db.execute(
        select(func.count(Tenant.id)).where(Tenant.status == TenantStatus.ACTIVE)
    ).scalar_one()

    return {
        "version": __version__,
        "checks": {
            "database": {
                "ok": db_ok,
                "detail": settings.panel_database_url.split("://", 1)[0],
            },
            "secret_encryption": {
                "ok": True,
                "detail": f"{encryption._kms_provider()} · {encryption.active_backend()}",
            },
            "audit_chain": {
                "ok": bool(chain.get("ok")),
                "detail": (
                    f"{chain.get('entries', 0)} entries chained"
                    if chain.get("ok")
                    else f"broken at #{chain.get('broken_at_seq')}"
                ),
            },
        },
        "background_loops": {
            "telemetry_poll_seconds": settings.telemetry_poll_seconds,
            "alert_poll_seconds": settings.alert_poll_seconds,
            "backup_poll_seconds": settings.backup_poll_seconds,
        },
        "fleet": {"total": total, "active": active},
    }


# ---- Users (operators) ------------------------------------------------------

@router.get("/operators")
def operators(request: Request, db: Session = Depends(get_db), actor: str = Depends(require_panel_token)):
    """Operators who have acted on the panel (distinct audit actors) plus the
    SSO group→role mapping that governs access. The panel has no user database —
    identity + roles come from the IdP (see Setup & Integration → SSO)."""
    rows = db.execute(
        select(AuditLog.actor, func.count(AuditLog.id), func.max(AuditLog.created_at))
        .group_by(AuditLog.actor)
        .order_by(func.max(AuditLog.created_at).desc())
        .limit(100)
    ).all()
    ops = [
        {"actor": a, "actions": int(n), "last_action_at": t.isoformat() if t else None}
        for a, n, t in rows
    ]
    from orchestrator import oidc

    cfg = oidc.effective_config(db)
    return {
        "operators": ops,
        # Reports the SSO actually in force, from whichever source configured it
        # — not just the retired federation row.
        "sso_enabled": cfg is not None,
        "sso_provider": (cfg.provider if cfg else None),
        "you": {"actor": actor, "role": resolve_role(request)},
    }


# ---- Portal-controlled security posture -----------------------------------


class ControlUpdate(BaseModel):
    value: bool | int
    confirm: bool = False


@router.get("/system/controls")
def list_controls(db: Session = Depends(get_db), _: str = Depends(require_operator)):
    """Every security control, its value, and whether it could be turned on now.

    `source` says whether the value came from the portal or the environment;
    `blocked_because` explains why a control cannot be enabled yet, so the UI can
    say "configure a KMS first" instead of offering a switch that would fail.
    """
    from orchestrator import platform_settings

    return {"controls": platform_settings.describe(db)}


@router.put("/system/controls/{key}")
def set_control(
    key: str,
    body: ControlUpdate,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    """Change one control. The portal is authoritative — a saved value overrides
    the environment — so weakening a control needs `confirm` and is audited."""
    from orchestrator import platform_settings

    try:
        result = platform_settings.set_control(db, key, body.value, actor, body.confirm)
    except platform_settings.ControlError as exc:
        raise HTTPException(422, str(exc)) from exc

    if result["effect"] == "rerender":
        result["rerender"] = _rerender_fleet_edge(db, actor)
    return result


def _rerender_fleet_edge(db: Session, actor: str) -> dict:
    """Re-render every active town's stack and reload the front proxy.

    The WAF and edge rate limits are baked into each town's Caddy site block, so
    flipping them is not a setting that takes effect on its own — the files have
    to be rewritten and the proxy told to re-read them.
    """
    from orchestrator import migrator, provisioner
    from orchestrator.models import Tenant as _Tenant

    towns = db.execute(
        select(_Tenant).where(_Tenant.status == TenantStatus.ACTIVE)).scalars().all()
    rendered, failed = 0, []
    for town in towns:
        try:
            provisioner.render_for_tenant(db, town, town.target_version or "latest")
            rendered += 1
        except Exception as exc:  # noqa: BLE001 — report, don't abort the fleet
            failed.append(f"{town.slug}: {exc}")
    reload_detail = migrator.reload_edge_proxy()
    audit.record(db, actor, "system.edge_rerendered", None,
                 rendered=rendered, failed=len(failed))
    db.commit()
    return {"rendered": rendered, "failed": failed, "proxy_reload": reload_detail}


# ---- Who provides (and pays for) each service key --------------------------


class KeyDefaults(BaseModel):
    assignments: dict[str, str]


@router.get("/platform/key-defaults")
def get_key_defaults(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    """The fleet-wide default for who supplies each service key, plus how many
    towns currently differ from it."""
    from orchestrator import key_catalog
    from orchestrator.models import Tenant as _Tenant

    cfg = get_config(db)
    defaults = key_catalog.normalize_assignments(
        (cfg.default_key_assignments if cfg else None) or {})

    towns = db.execute(select(_Tenant).where(
        _Tenant.status.notin_([TenantStatus.DECOMMISSIONED, TenantStatus.MIGRATED])
    )).scalars().all()

    drift: dict[str, int] = {}
    for service_id, owner in defaults.items():
        differing = sum(
            1 for t in towns
            if key_catalog.normalize_assignments(t.key_assignments).get(service_id) != owner
        )
        if differing:
            drift[service_id] = differing

    return {
        "services": key_catalog.ASSIGNABLE_SERVICES,
        "owners": list(key_catalog.OWNERS),
        "defaults": defaults,
        "drift": drift,
        "town_count": len(towns),
    }


@router.put("/platform/key-defaults")
def set_key_defaults(
    body: KeyDefaults,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    """Set the default new towns inherit. Deliberately does NOT touch existing
    towns — changing who pays for Maps across a live fleet is a billing event,
    not a settings change, so it has its own action below."""
    from orchestrator import key_catalog

    cfg = get_config(db)
    if not cfg:
        cfg = PlatformConfig(id="default")
        db.add(cfg)
    cfg.default_key_assignments = key_catalog.normalize_assignments(body.assignments)
    audit.record(db, actor, "platform.key_defaults_set", None,
                 assignments=cfg.default_key_assignments)
    db.commit()
    return {"defaults": cfg.default_key_assignments}


@router.post("/platform/key-defaults/apply-to-all")
def apply_key_defaults(
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    """Push the default onto every live town, overwriting per-town choices.

    Separate from saving the default because this re-points real billing. Each
    town that changes is named in the audit entry.
    """
    from orchestrator import key_catalog
    from orchestrator.models import Tenant as _Tenant

    cfg = get_config(db)
    defaults = key_catalog.normalize_assignments(
        (cfg.default_key_assignments if cfg else None) or {})

    towns = db.execute(select(_Tenant).where(
        _Tenant.status.notin_([TenantStatus.DECOMMISSIONED, TenantStatus.MIGRATED])
    )).scalars().all()

    changed = []
    for town in towns:
        current = key_catalog.normalize_assignments(town.key_assignments)
        if current != defaults:
            town.key_assignments = dict(defaults)
            changed.append(town.slug)

    audit.record(db, actor, "platform.key_defaults_applied", None,
                 changed=changed, count=len(changed))
    db.commit()
    return {"changed": changed, "count": len(changed)}
