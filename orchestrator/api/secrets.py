"""B5 — secrets brokering. Platform-managed keys only; write-only surface."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator import audit
from orchestrator.db import get_db
from orchestrator.key_catalog import STATE, normalize_assignments, service_for_key
from orchestrator.models import PlatformSecret, Tenant
from orchestrator.provisioner import set_platform_secret
from orchestrator.schemas import SecretOut, SecretWrite
from orchestrator.secrets_policy import is_platform_managed
from orchestrator.security import require_panel_token

router = APIRouter(prefix="/api/tenants/{tenant_id}/secrets", tags=["secrets"])


def _tenant(db: Session, tenant_id: str) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    return tenant


@router.get("", response_model=list[SecretOut])
def list_secret_names(
    tenant_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_panel_token),
):
    """Names + timestamps only — the panel never returns secret values."""
    _tenant(db, tenant_id)
    rows = db.execute(
        select(PlatformSecret).where(PlatformSecret.tenant_id == tenant_id)
    ).scalars().all()
    return [SecretOut(key_name=r.key_name, updated_at=r.updated_at) for r in rows]


@router.put("/{key_name}", response_model=SecretOut, status_code=201)
def put_secret(
    tenant_id: str,
    key_name: str,
    body: SecretWrite,
    db: Session = Depends(get_db),
    actor: str = Depends(require_panel_token),
):
    tenant = _tenant(db, tenant_id)
    key = key_name.strip().upper()

    # The panel brokers a key only if it is infrastructure (always state-owned)
    # OR it belongs to an assignable service this town has assigned to "state".
    # Otherwise the town owns it and enters it in its own instance.
    if not is_platform_managed(key):
        service = service_for_key(key)
        assignments = normalize_assignments(tenant.key_assignments)
        if not service or assignments.get(service["id"]) != STATE:
            raise HTTPException(
                422,
                f"'{key}' is the town's responsibility — assign its service to the "
                "state on the key-responsibility matrix before brokering it here.",
            )
    set_platform_secret(db, tenant_id, key, body.value)
    audit.record(db, actor, "secret.written", tenant_id, key_name=key)
    db.commit()
    row = db.execute(
        select(PlatformSecret).where(
            PlatformSecret.tenant_id == tenant_id, PlatformSecret.key_name == key
        )
    ).scalar_one()
    return SecretOut(key_name=row.key_name, updated_at=row.updated_at)


@router.delete("/{key_name}", status_code=204)
def delete_secret(
    tenant_id: str,
    key_name: str,
    db: Session = Depends(get_db),
    actor: str = Depends(require_panel_token),
):
    _tenant(db, tenant_id)
    key = key_name.strip().upper()
    row = db.execute(
        select(PlatformSecret).where(
            PlatformSecret.tenant_id == tenant_id, PlatformSecret.key_name == key
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Secret not found")
    db.delete(row)
    audit.record(db, actor, "secret.deleted", tenant_id, key_name=key)
    db.commit()
