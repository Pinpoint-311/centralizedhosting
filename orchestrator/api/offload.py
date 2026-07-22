"""Municipality offload: generate a self-host bundle and manage the migration
lifecycle (active → migrating → migrated), then the town can be decommissioned."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from orchestrator import audit, offload, provisioner
from orchestrator.db import get_db
from orchestrator.models import Tenant, TenantStatus
from orchestrator.security import require_approver

router = APIRouter(prefix="/api/tenants", tags=["offload"])

_OFFLOADABLE = {TenantStatus.ACTIVE, TenantStatus.OFFLINE, TenantStatus.SUSPENDED, TenantStatus.MIGRATING}


def _tenant(db: Session, tenant_id: str) -> Tenant:
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(404, "Tenant not found")
    return t


@router.post("/{tenant_id}/offload")
def start_offload(tenant_id: str, db: Session = Depends(get_db), actor: str = Depends(require_approver)):
    """Generate the self-host bundle (compose + env + Caddyfile + runbook, plus a
    data snapshot when the stack is applied) and mark the town migrating."""
    t = _tenant(db, tenant_id)
    if t.status not in _OFFLOADABLE:
        raise HTTPException(409, f"Cannot offload a '{t.status}' town")

    secrets = provisioner._secrets_bundle(db, t)
    rel = provisioner.release_for_version(db, offload._version(t))
    offload.build_bundle(
        t, secrets,
        backend_digest=rel.backend_digest if rel else None,
        frontend_digest=rel.frontend_digest if rel else None,
    )
    includes_data = offload.export_data(t)
    # Re-render the runbook now that we know whether data is bundled.
    offload.build_bundle(
        t, secrets, includes_data=includes_data,
        backend_digest=rel.backend_digest if rel else None,
        frontend_digest=rel.frontend_digest if rel else None,
    )
    archive = offload.package(t, includes_data=includes_data)

    t.status = TenantStatus.MIGRATING
    audit.record(db, actor, "tenant.offload_started", t.id, includes_data=includes_data)
    db.commit()
    return {
        "status": t.status,
        "includes_data": includes_data,
        "bundle": ["docker-compose.yml", ".env", "Caddyfile", "MIGRATION_RUNBOOK.md"]
        + (["data/dump.sql"] if includes_data else []),
        "download_path": f"/api/tenants/{t.id}/offload/bundle",
        "archive_bytes": archive.stat().st_size if archive.exists() else 0,
    }


@router.get("/{tenant_id}/offload/preview")
def preview_offload(tenant_id: str, db: Session = Depends(get_db), _: str = Depends(require_approver)):
    from orchestrator.config import settings

    t = _tenant(db, tenant_id)
    secrets = provisioner._secrets_bundle(db, t)
    return offload.preview(t, secrets, includes_data=settings.apply_stacks)


@router.get("/{tenant_id}/offload/bundle")
def download_bundle(tenant_id: str, db: Session = Depends(get_db), _: str = Depends(require_approver)):
    t = _tenant(db, tenant_id)
    archive = offload.bundle_archive_path(t)
    if not archive.exists():
        raise HTTPException(404, "No bundle generated yet — start the offload first")
    return FileResponse(
        str(archive), media_type="application/gzip",
        filename=f"{t.slug}-selfhost-bundle.tar.gz",
    )


@router.post("/{tenant_id}/offload/complete")
def complete_offload(tenant_id: str, db: Session = Depends(get_db), actor: str = Depends(require_approver)):
    """Mark the town migrated once it confirms it's live on its own infra. Data
    is retained on the platform (read-only) until an explicit decommission."""
    t = _tenant(db, tenant_id)
    if t.status != TenantStatus.MIGRATING:
        raise HTTPException(409, "Town is not currently migrating")
    t.status = TenantStatus.MIGRATED
    audit.record(db, actor, "tenant.offload_completed", t.id)
    db.commit()
    return {"status": t.status}


@router.post("/{tenant_id}/offload/cancel")
def cancel_offload(tenant_id: str, db: Session = Depends(get_db), actor: str = Depends(require_approver)):
    t = _tenant(db, tenant_id)
    if t.status not in (TenantStatus.MIGRATING, TenantStatus.MIGRATED):
        raise HTTPException(409, "No offload in progress")
    t.status = TenantStatus.ACTIVE
    audit.record(db, actor, "tenant.offload_cancelled", t.id)
    db.commit()
    return {"status": t.status}
