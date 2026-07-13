"""Panel auth, at-rest encryption for brokered secrets, break-glass tokens."""

import base64
import hashlib
import hmac
import json
import secrets as pysecrets
from datetime import datetime, timedelta, timezone

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


# ------------------------------------------------------------ break-glass token

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _sign(payload: bytes, signing_key: str) -> str:
    return _b64(hmac.new(signing_key.encode(), payload, hashlib.sha256).digest())


def mint_break_glass_token(
    tenant_id: str, actor: str, token_id: str, expires_at: datetime, signing_key: str
) -> str:
    """Short-lived signed token the app accepts only in managed mode (plan A8),
    logged town-side as actor_type="state_ops".

    Signed with the town's own PROVISIONING_TOKEN — a secret the town instance
    already holds — so the app can verify it without any extra key
    distribution, and a token minted for one town is useless against another.
    """
    payload = json.dumps(
        {
            "typ": "state_ops_break_glass",
            "tid": tenant_id,
            "actor": actor,
            "jti": token_id,
            "exp": int(expires_at.replace(tzinfo=timezone.utc).timestamp()),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"{_b64(payload)}.{_sign(payload, signing_key)}"


def verify_break_glass_token(token: str, signing_key: str) -> dict:
    """Verify signature + expiry; raises ValueError on any problem."""
    try:
        payload_b64, sig = token.split(".", 1)
        payload = _unb64(payload_b64)
    except Exception as exc:
        raise ValueError("malformed token") from exc
    if not hmac.compare_digest(sig, _sign(payload, signing_key)):
        raise ValueError("bad signature")
    claims = json.loads(payload)
    if claims.get("typ") != "state_ops_break_glass":
        raise ValueError("wrong token type")
    if datetime.now(timezone.utc).timestamp() > claims["exp"]:
        raise ValueError("expired")
    return claims


def clamp_break_glass_expiry(minutes: int) -> datetime:
    minutes = max(1, min(minutes, settings.break_glass_max_minutes))
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=minutes)
