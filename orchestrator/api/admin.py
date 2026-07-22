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

    from orchestrator.encryption import _kms_provider, active_backend

    return {
        "actor": actor,
        "role": resolve_role(request),
        "auth_method": "sso" if _session_from_request(request) else "token",
        # Uniform with the app: which KMS is selected and which backend actually
        # wraps the data key ('google'|'azure'|'aws'|'local').
        "kms_provider": _kms_provider(),
        "kms_backend": active_backend(),
        "require_signed_images": settings.require_signed_images,
    }


@router.post("/maintenance/reencrypt-secrets")
def reencrypt_secrets(
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(require_approver),
):
    """Re-encrypt all stored secrets under the current key — run after rotating
    the KMS key or switching provider. Admin/approver only."""
    from orchestrator.encryption import active_backend

    count = provisioner.reencrypt_all_secrets(db)
    backend = active_backend()
    audit.record(db, actor, "maintenance.secrets_reencrypted", None,
                 count=count, kms_backend=backend)
    db.commit()
    return {"reencrypted": count, "kms_backend": backend}
