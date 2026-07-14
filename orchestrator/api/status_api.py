"""Public status page + operator-managed announcements (maintenance/incidents).

The public `/api/status` endpoint is unauthenticated and metadata-only: overall
health, region-level availability (never town-by-town), and active announcements.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator import audit, insights
from orchestrator.config import settings
from orchestrator.db import get_db
from orchestrator.models import Announcement, Tenant, TenantStatus, utcnow
from orchestrator.schemas import AnnouncementCreate, AnnouncementOut
from orchestrator.security import require_operator, require_panel_token

router = APIRouter(prefix="/api", tags=["status"])


def _active_announcements(db: Session):
    now = utcnow()
    out = []
    for a in db.execute(select(Announcement).where(Announcement.active).order_by(Announcement.created_at.desc())).scalars():
        if a.starts_at and a.starts_at > now:
            continue
        if a.ends_at and a.ends_at < now:
            continue
        out.append(a)
    return out


@router.get("/status")
def public_status(db: Session = Depends(get_db)):
    """PUBLIC — overall program health, region availability, announcements.
    No town-by-town detail; no auth."""
    tenants = db.execute(select(Tenant).where(Tenant.status == TenantStatus.ACTIVE)).scalars().all()
    total = len(tenants)
    # Region availability from the (already region-only, min-cell-suppressed)
    # SLA rollup would go here; for the public page we report program-level.
    operational = sum(1 for t in tenants if t.status == TenantStatus.ACTIVE)
    anns = _active_announcements(db)
    overall = "operational"
    if any(a.severity == "incident" for a in anns):
        overall = "incident"
    elif any(a.severity == "maintenance" for a in anns):
        overall = "maintenance"
    return {
        "program": f"Pinpoint 311 · {settings.base_domain}",
        "overall": overall,
        "municipalities_operational": operational,
        "municipalities_total": total,
        "announcements": [
            {"title": a.title, "body": a.body, "severity": a.severity,
             "starts_at": a.starts_at.isoformat() if a.starts_at else None,
             "ends_at": a.ends_at.isoformat() if a.ends_at else None}
            for a in anns
        ],
    }


@router.get("/announcements", response_model=list[AnnouncementOut])
def list_announcements(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    return db.execute(select(Announcement).order_by(Announcement.created_at.desc())).scalars().all()


@router.post("/announcements", response_model=AnnouncementOut, status_code=201)
def create_announcement(
    body: AnnouncementCreate,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    a = Announcement(title=body.title, body=body.body, severity=body.severity,
                     active=body.active, created_by=actor)
    db.add(a)
    audit.record(db, actor, "announcement.created", None, title=body.title, severity=body.severity)
    db.commit()
    return a


@router.delete("/announcements/{announcement_id}", status_code=204)
def delete_announcement(
    announcement_id: str,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    a = db.get(Announcement, announcement_id)
    if not a:
        raise HTTPException(404, "Announcement not found")
    db.delete(a)
    audit.record(db, actor, "announcement.deleted", None, title=a.title)
    db.commit()
