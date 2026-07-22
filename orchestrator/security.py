"""Panel auth and at-rest encryption for brokered secrets."""

import hmac
import json
import secrets as pysecrets
from datetime import datetime, timedelta, timezone

import jwt
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


# ---------------------------------------------------------------- SSO session

_SESSION_TYP = "panel_session"


def mint_session(actor: str, role: str) -> str:
    """A signed (HS256) session token for an SSO-authenticated operator, carried
    in an HttpOnly cookie. Signed with PANEL_SECRET_KEY."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": actor[:150],
        "role": role if role in ROLES else "viewer",
        "typ": _SESSION_TYP,
        "iat": now,
        "exp": now + timedelta(minutes=max(1, settings.session_ttl_minutes)),
    }
    return jwt.encode(payload, settings.panel_secret_key, algorithm="HS256")


def verify_session(token: str) -> dict | None:
    """Validate a session cookie; return {actor, role} or None."""
    try:
        claims = jwt.decode(token, settings.panel_secret_key, algorithms=["HS256"])
    except Exception:
        return None
    if claims.get("typ") != _SESSION_TYP:
        return None
    role = claims.get("role")
    if role not in ROLES:
        return None
    return {"actor": claims.get("sub") or "sso-operator", "role": role}


def _session_from_request(request: Request) -> dict | None:
    token = request.cookies.get(settings.session_cookie_name)
    return verify_session(token) if token else None


def resolve_role(request: Request) -> str:
    """Effective role for this request. An SSO session's role wins; otherwise
    the highest role among the operator's mapped groups (from the trusted
    ROLES_HEADER), else DEFAULT_OPERATOR_ROLE."""
    session = _session_from_request(request)
    if session:
        return session["role"]
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
        # 1) SSO session cookie (if present and valid) authenticates on its own.
        session = _session_from_request(request)
        if session:
            actor, role = session["actor"], session["role"]
        else:
            # 2) Shared token + trusted OIDC-proxy headers (fail-closed).
            actor = _authenticate(request, x_panel_token)
            role = resolve_role(request)
        if _RANK[role] < _RANK[minimum]:
            raise HTTPException(403, f"Requires '{minimum}' role; you have '{role}'.")
        return actor

    return dependency


# viewer-level = any authenticated operator. Kept as the historical name so
# read-only routes need no churn.
require_panel_token = require_role("viewer")
require_operator = require_role("operator")
require_approver = require_role("approver")
require_admin = require_role("admin")


# ------------------------------------------------------- secrets at-rest crypto
# Uniform with the Pinpoint 311 app: brokered/shared secrets are envelope-
# encrypted (AES-256-GCM DEK wrapped by the configured KMS — Google/AWS/Azure —
# or a PANEL_SECRET_KEY-derived key), producing a self-describing ``pii2:``
# token. See orchestrator/pii_crypto.py and orchestrator/encryption.py.

import re as _re

_LEGACY_VERSIONED = _re.compile(r"^v(\d+):(.+)$", _re.DOTALL)


def encrypt_value(plaintext: str) -> str:
    """Envelope-encrypt a secret at rest. Returns a ``pii2:`` token. Fails
    closed to the local key only when REQUIRE_KMS is not set."""
    from orchestrator import encryption, pii_crypto

    try:
        return pii_crypto.encrypt(plaintext)
    except Exception:
        if encryption._kms_required():
            raise  # never silently downgrade when a real KMS is mandated
        return encryption.encrypt(plaintext)  # Fernet fallback (gAAAA…)


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a value written by any scheme the panel has used: the current
    ``pii2:`` envelope, legacy Azure per-field (``akv:``), the panel's earlier
    versioned Fernet (``v<n>:``), or plain Fernet (``gAAAA…``)."""
    from orchestrator import encryption, pii_crypto

    if ciphertext.startswith(pii_crypto.PII_V2_PREFIX):
        return pii_crypto.decrypt(ciphertext)
    if ciphertext.startswith(encryption.AZURE_ENCRYPTED_PREFIX):
        from orchestrator import azure_keyvault

        return azure_keyvault.decrypt(ciphertext[len(encryption.AZURE_ENCRYPTED_PREFIX):])
    m = _LEGACY_VERSIONED.match(ciphertext)
    if m:
        # Panel's pre-uniformity versioned-Fernet secrets (v1 == sha256 of
        # PANEL_SECRET_KEY; later versions mixed the version into the material).
        import base64 as _b64
        import hashlib as _hl

        from cryptography.fernet import Fernet

        version, token = int(m.group(1)), m.group(2)
        material = (settings.panel_secret_key if version <= 1
                    else f"{settings.panel_secret_key}:v{version}").encode()
        fernet = Fernet(_b64.urlsafe_b64encode(_hl.sha256(material).digest()))
        return fernet.decrypt(token.encode()).decode()
    return encryption.decrypt(ciphertext)  # plain Fernet


def generate_secret(nbytes: int = 32) -> str:
    return pysecrets.token_hex(nbytes)
