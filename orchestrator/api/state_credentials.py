"""Shared state credential pool — entered once, plugged into every town whose
key-responsibility matrix sets the owning service to ``state_shared``.
Write-only: values are encrypted at rest and never returned."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator import audit
from orchestrator.db import get_db
from orchestrator.key_catalog import all_assignable_keys
from orchestrator.models import StateCredential
from orchestrator.provisioner import set_state_credential
from orchestrator.schemas import SecretOut, SecretWrite
from orchestrator.security import require_operator, require_panel_token

router = APIRouter(prefix="/api/state-credentials", tags=["state-credentials"])


@router.get("", response_model=list[SecretOut])
def list_state_credentials(
    db: Session = Depends(get_db),
    _: str = Depends(require_panel_token),
):
    """Configured shared-credential key names + timestamps (never values)."""
    rows = db.execute(select(StateCredential)).scalars().all()
    return [SecretOut(key_name=r.key_name, updated_at=r.updated_at) for r in rows]


@router.put("/{key_name}", response_model=SecretOut, status_code=201)
def put_state_credential(
    key_name: str,
    body: SecretWrite,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    key = key_name.strip().upper()
    if key not in all_assignable_keys():
        raise HTTPException(
            422,
            f"'{key}' is not an assignable-service key — the shared pool only holds "
            "provider credentials that towns can plug into.",
        )
    set_state_credential(db, key, body.value)
    audit.record(db, actor, "state_credential.written", None, key_name=key)
    db.commit()
    row = db.execute(
        select(StateCredential).where(StateCredential.key_name == key)
    ).scalar_one()
    return SecretOut(key_name=row.key_name, updated_at=row.updated_at)


@router.delete("/{key_name}", status_code=204)
def delete_state_credential(
    key_name: str,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    key = key_name.strip().upper()
    row = db.execute(
        select(StateCredential).where(StateCredential.key_name == key)
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "State credential not found")
    db.delete(row)
    audit.record(db, actor, "state_credential.deleted", None, key_name=key)
    db.commit()
