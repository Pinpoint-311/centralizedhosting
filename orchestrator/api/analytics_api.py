"""Region-level 311 analytics (never town-by-town), the canonical service
taxonomy + per-town mappings, and the compliance posture dashboard."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator import audit, insights, managed_settings
from orchestrator.config import settings
from orchestrator.db import get_db
from orchestrator.models import (
    CategoryMapping,
    ServiceCategory,
    Tenant,
    TenantStatus,
)
from orchestrator.queries import latest_release
from orchestrator.security import require_operator, require_panel_token

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/analytics")
def analytics(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    """311 analytics — REGION-LEVEL ONLY. Never returns an individual town's
    figures (see insights.analytics)."""
    return insights.analytics(db, region_label=settings.region_label.lower())


@router.get("/taxonomy")
def taxonomy(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    cats = db.execute(select(ServiceCategory).order_by(ServiceCategory.group, ServiceCategory.label)).scalars().all()
    return {"categories": [{"code": c.code, "label": c.label, "group": c.group} for c in cats]}


class MappingUpdate(BaseModel):
    mappings: dict[str, str]  # local category (name/code) -> canonical code


@router.get("/tenants/{tenant_id}/category-mappings")
def get_mappings(tenant_id: str, db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    rows = db.execute(select(CategoryMapping).where(CategoryMapping.tenant_id == tenant_id)).scalars().all()
    return {"mappings": {r.local_key: r.canonical_code for r in rows}}


@router.put("/tenants/{tenant_id}/category-mappings")
def put_mappings(
    tenant_id: str,
    body: MappingUpdate,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    if not db.get(Tenant, tenant_id):
        raise HTTPException(404, "Tenant not found")
    valid = {c.code for c in db.execute(select(ServiceCategory)).scalars()}
    for local, code in body.mappings.items():
        if code not in valid:
            raise HTTPException(422, f"Unknown canonical code: {code}")
        existing = db.execute(
            select(CategoryMapping).where(
                CategoryMapping.tenant_id == tenant_id, CategoryMapping.local_key == local
            )
        ).scalar_one_or_none()
        if existing:
            existing.canonical_code = code
        else:
            db.add(CategoryMapping(tenant_id=tenant_id, local_key=local, canonical_code=code))
    audit.record(db, actor, "tenant.category_mappings_updated", tenant_id, count=len(body.mappings))
    db.commit()
    return {"mappings": body.mappings}


@router.get("/compliance/summary")
def compliance(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    """Per-town security/compliance posture — the state's oversight view. This
    is infrastructure/policy metadata (not resident data): encryption, backups,
    version currency, retention, accessibility, legal hold."""
    tenants = db.execute(select(Tenant).where(Tenant.status != TenantStatus.DECOMMISSIONED)).scalars().all()
    latest = latest_release(db)
    rows = []
    for t in tenants:
        ms = managed_settings.normalize(t.managed_settings)
        checks = {
            "encryption": bool(t.kms_key_ref),
            "version_current": bool(latest and t.running_version == latest.version) if latest else True,
            "retention_set": bool(ms.get("retention_days")),
            "mfa_required": bool(ms.get("require_mfa")),
            "accessibility_statement": bool(ms.get("accessibility_statement_url")),
            "log_shipping": bool(ms.get("log_shipping_target")),
        }
        score = round(sum(1 for v in checks.values() if v) / len(checks) * 100)
        rows.append({
            "id": t.id, "slug": t.slug, "name": t.name, "county": t.county,
            "checks": checks, "score": score, "legal_hold": bool(ms.get("legal_hold")),
        })
    rows.sort(key=lambda r: r["score"])
    fleet = {}
    if rows:
        for k in rows[0]["checks"]:
            fleet[k] = sum(1 for r in rows if r["checks"][k])
    return {"towns": rows, "total": len(rows), "passing_by_check": fleet}
