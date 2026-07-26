"""Hosting-provider admin — the entity running this control plane (a state,
county, city, university, or agency), NOT a hosted municipality.

Mirrors the Pinpoint 311 app's admin console, grouped the same way:
  Branding & Setup   → platform branding + organization identity
  System & Compliance → effective system settings + system health

Municipality management (tenants) and fleet management (insights/operations)
live elsewhere; this is the provider's own setup.
"""

from fastapi import APIRouter, Depends, Request
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

@router.get("/system/config")
def system_config(_: str = Depends(require_operator)):
    """Effective operational configuration (read-only; env-driven)."""
    from orchestrator import encryption

    s = settings
    return {
        "deployment": {
            "base_domain": s.base_domain,
            "apply_stacks": s.apply_stacks,
            "backend_image": s.backend_image,
            "frontend_image": s.frontend_image,
        },
        "polling": {
            "telemetry_poll_seconds": s.telemetry_poll_seconds,
            "alert_poll_seconds": s.alert_poll_seconds,
            "telemetry_retention_days": s.telemetry_retention_days,
        },
        "security": {
            "kms_provider": encryption._kms_provider(),
            "kms_backend": encryption.active_backend(),
            "require_kms": encryption._kms_required(),
            "require_signed_images": s.require_signed_images,
            "cosign_verify": s.cosign_verify,
            "rate_limit_rpm": s.rate_limit_rpm,
            "waf_enabled": s.waf_enabled,
            "ssl_check_enabled": s.ssl_check_enabled,
        },
        "backups": {
            "enabled": s.backups_enabled,
            "poll_seconds": s.backup_poll_seconds,
            "retention_days": s.backup_retention_days,
        },
        "intake": {"public_requests_enabled": s.public_requests_enabled},
    }


@router.get("/system/proactive")
def system_proactive(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    """Leading-indicator health — warns before something fails (disk, memory,
    database, backup freshness, audit chain). Ported from the app's engine."""
    from orchestrator import proactive_health

    return proactive_health.evaluate(db)


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
    fed = db.get(FederationConfig, "default")
    return {
        "operators": ops,
        "role_map": (fed.group_role_map if fed else {}) or {},
        "default_role": settings.default_operator_role,
        "sso_enabled": bool(fed and fed.enabled),
        "you": {"actor": actor, "role": resolve_role(request)},
    }
