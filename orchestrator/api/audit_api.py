"""B6 — read side of the central compliance audit trail."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator import audit as audit_svc
from orchestrator.db import get_db
from orchestrator.models import AuditAnchor, AuditLog
from orchestrator.schemas import AuditOut
from orchestrator.security import require_operator, require_panel_token

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=list[AuditOut])
def list_audit(
    tenant_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
    db: Session = Depends(get_db),
    _: str = Depends(require_panel_token),
):
    query = select(AuditLog).order_by(AuditLog.seq.desc()).limit(limit)
    if tenant_id:
        query = query.where(AuditLog.tenant_id == tenant_id)
    if action:
        query = query.where(AuditLog.action == action)
    return db.execute(query).scalars().all()


@router.get("/verify")
def verify_audit(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    """Recompute the tamper-evident hash chain; report the first break if any."""
    return audit_svc.verify_chain(db)


@router.post("/anchor")
def anchor_audit(db: Session = Depends(get_db), _: str = Depends(require_operator)):
    """Record a tamper-anchor of the chain head + count (also logged to stdout
    for off-host aggregation) — uniform with the app's audit anchor."""
    result = audit_svc.anchor_chain(db)
    db.commit()
    return result


@router.get("/anchors")
def list_anchors(limit: int = Query(default=30, le=200), db: Session = Depends(get_db),
                 _: str = Depends(require_panel_token)):
    rows = db.execute(
        select(AuditAnchor).order_by(AuditAnchor.created_at.desc()).limit(limit)
    ).scalars().all()
    return [{"head": r.head, "count": r.count,
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]
