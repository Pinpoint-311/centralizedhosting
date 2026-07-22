"""PITR backup endpoints: take a base snapshot and list a town's backup catalog."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from orchestrator import backups
from orchestrator.config import settings
from orchestrator.db import get_db
from orchestrator.models import BackupRecord, Tenant
from orchestrator.security import require_operator, require_panel_token

router = APIRouter(prefix="/api/tenants", tags=["backups"])


def _serialize(r: BackupRecord) -> dict:
    return {
        "id": r.id,
        "kind": r.kind,
        "status": r.status,
        "path": r.path,
        "size_bytes": r.size_bytes,
        "detail": r.detail,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _tenant(db: Session, tenant_id: str) -> Tenant:
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(404, "Tenant not found")
    return t


@router.post("/{tenant_id}/backup")
def take_backup(tenant_id: str, db: Session = Depends(get_db), actor: str = Depends(require_operator)):
    t = _tenant(db, tenant_id)
    rec = backups.run_base_backup(db, t, actor)
    return _serialize(rec)


@router.get("/{tenant_id}/backups")
def list_backups(tenant_id: str, db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    _tenant(db, tenant_id)
    return {
        "backups_enabled": settings.backups_enabled,
        "s3_configured": backups.s3_configured(),
        "backups": [_serialize(r) for r in backups.list_backups(db, tenant_id)],
    }
