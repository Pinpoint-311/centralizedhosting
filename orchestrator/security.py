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

def require_panel_token(request: Request, x_panel_token: str = Header(default="")) -> str:
    """Operator auth for every panel API route. Fails closed when unconfigured;
    constant-time compare per the plan's A4 guidance.

    Returns the operator identity for the audit trail: when the deployment sets
    OPERATOR_HEADER (populated by a trusted OIDC/SSO reverse proxy), the real
    authenticated user is recorded; otherwise a generic label."""
    if not settings.panel_api_token:
        raise HTTPException(503, "Panel API token not configured — set PANEL_API_TOKEN")
    if not hmac.compare_digest(x_panel_token, settings.panel_api_token):
        raise HTTPException(401, "Invalid panel token")
    if settings.operator_header:
        who = request.headers.get(settings.operator_header, "").strip()
        if who:
            return who[:150]
    return "panel-operator"


# ------------------------------------------------------- secrets at-rest crypto

def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.panel_secret_key.encode()).digest())
    return Fernet(key)


def encrypt_value(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()


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
