"""Panel auth and at-rest encryption for brokered secrets."""

import hmac
import json
import secrets as pysecrets

from cryptography.fernet import Fernet
from fastapi import Header, HTTPException, Request

from orchestrator.config import settings


# ---------------------------------------------------------------- operator auth

def _authenticate(request: Request, x_panel_token: str) -> str:
    """Validate the shared token (fail-closed, constant-time) and resolve the
    operator identity for the audit trail from the trusted OIDC-proxy header."""
    if not settings.panel_api_token:
        raise HTTPException(503, "Panel API token not configured — set PANEL_API_TOKEN")
    if not hmac.compare_digest(x_panel_token, settings.panel_api_token):
        raise HTTPException(401, "Invalid panel token")
    if settings.operator_header:
        who = request.headers.get(settings.operator_header, "").strip()
        if who:
            return who[:150]
    return "panel-operator"


# ---------------------------------------------------------------- RBAC

ROLES = ("viewer", "operator", "approver", "admin")
_RANK = {r: i for i, r in enumerate(ROLES)}


def _role_group_map() -> dict[str, str]:
    if not settings.role_group_map:
        return {}
    try:
        raw = json.loads(settings.role_group_map)
        return {str(k): str(v) for k, v in raw.items() if v in ROLES}
    except Exception:
        return {}


def resolve_role(request: Request) -> str:
    """Effective role for this request. Highest role among the operator's
    mapped groups (from the trusted ROLES_HEADER), else DEFAULT_OPERATOR_ROLE."""
    mapping = _role_group_map()
    if settings.roles_header and mapping:
        raw = request.headers.get(settings.roles_header, "")
        groups = [g.strip() for g in raw.replace(",", " ").split() if g.strip()]
        best = -1
        for g in groups:
            role = mapping.get(g)
            if role and _RANK[role] > best:
                best = _RANK[role]
        if best >= 0:
            return ROLES[best]
        # A groups header is present but none map -> lowest privilege, fail safe.
        return "viewer"
    default = settings.default_operator_role
    return default if default in ROLES else "admin"


def require_role(minimum: str):
    """Dependency factory: authenticate, then require role >= `minimum`.
    Returns the operator identity string (used as the audit actor)."""

    def dependency(request: Request, x_panel_token: str = Header(default="")) -> str:
        actor = _authenticate(request, x_panel_token)
        role = resolve_role(request)
        if _RANK[role] < _RANK[minimum]:
            raise HTTPException(
                403, f"Requires '{minimum}' role; you have '{role}'."
            )
        return actor

    return dependency


# viewer-level = any authenticated operator. Kept as the historical name so
# read-only routes need no churn.
require_panel_token = require_role("viewer")
require_operator = require_role("operator")
require_approver = require_role("approver")


# ------------------------------------------------------- secrets at-rest crypto

def encrypt_value(plaintext: str) -> str:
    """Encrypt with the active key version; ciphertext is version-tagged
    (``v<n>:<token>``) so rotation can decrypt older values."""
    from orchestrator import key_provider

    version = settings.panel_kek_version
    token = key_provider.for_version(version).encrypt(plaintext.encode()).decode()
    return f"v{version}:{token}"


def decrypt_value(ciphertext: str) -> str:
    from orchestrator import key_provider

    if ciphertext.startswith("v") and ":" in ciphertext:
        tag, token = ciphertext.split(":", 1)
        try:
            version = int(tag[1:])
        except ValueError:
            version, token = 1, ciphertext  # not a version tag after all
    else:
        version, token = 1, ciphertext  # legacy, pre-rotation ciphertext
    return key_provider.for_version(version).decrypt(token.encode()).decode()


def generate_secret(nbytes: int = 32) -> str:
    return pysecrets.token_hex(nbytes)
