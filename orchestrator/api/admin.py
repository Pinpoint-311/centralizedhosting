"""Panel administration: identity/role introspection and key rotation."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from orchestrator import audit, provisioner
from orchestrator.config import settings
from orchestrator.db import get_db
from orchestrator.security import require_approver, require_panel_token, resolve_role

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/whoami")
def whoami(request: Request, actor: str = Depends(require_panel_token)):
    """The authenticated operator and effective role — the UI uses the role to
    show/hide privileged actions (defense-in-depth on top of server enforcement)."""
    from orchestrator.security import _session_from_request

    return {
        "actor": actor,
        "role": resolve_role(request),
        "auth_method": "sso" if _session_from_request(request) else "token",
        "key_provider": settings.key_provider,
        "require_signed_images": settings.require_signed_images,
    }


@router.post("/maintenance/reencrypt-secrets")
def reencrypt_secrets(
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_approver),
):
    """Re-encrypt all stored secrets with the active key version — the second
    half of a key rotation (after bumping PANEL_KEK_VERSION). Admin/approver only."""
    count = provisioner.reencrypt_all_secrets(db)
    audit.record(db, actor, "maintenance.secrets_reencrypted", None,
                 count=count, key_version=settings.panel_kek_version)
    db.commit()
    return {"reencrypted": count, "key_version": settings.panel_kek_version}
