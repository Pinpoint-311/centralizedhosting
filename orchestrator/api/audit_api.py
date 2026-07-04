"""B6 — read side of the central compliance audit trail."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.db import get_db
from orchestrator.models import AuditLog
from orchestrator.schemas import AuditOut
from orchestrator.security import require_panel_token

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=list[AuditOut])
def list_audit(
    tenant_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
    db: Session = Depends(get_db),
    _: str = Depends(require_panel_token),
):
    query = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if tenant_id:
        query = query.where(AuditLog.tenant_id == tenant_id)
    if action:
        query = query.where(AuditLog.action == action)
    return db.execute(query).scalars().all()
