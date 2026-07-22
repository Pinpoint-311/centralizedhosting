"""Azure Key Vault key-wrapping over the REST API — ported from the app for
uniform KMS setup. Plain httpx + AAD client-credentials, no azure SDK; works
against commercial and Azure Government via AZURE_AUTHORITY / AZURE_KEYVAULT_SCOPE.

Same env vars as the app: AZURE_TENANT_ID, AZURE_KEYVAULT_CLIENT_ID,
AZURE_KEYVAULT_CLIENT_SECRET, AZURE_KEYVAULT_URL, AZURE_KEYVAULT_KEY (+ optional
AZURE_AUTHORITY, AZURE_KEYVAULT_SCOPE, AZURE_KEYVAULT_API_VERSION). Wraps only
the DEK (see pii_crypto)."""

import base64
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_token_cache: dict = {}


def _cfg(key: str) -> Optional[str]:
    from orchestrator.encryption import _get_config_sync

    return _get_config_sync(key)


def _b64url_nopad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def is_configured() -> bool:
    return bool(_cfg("AZURE_TENANT_ID") and _cfg("AZURE_KEYVAULT_CLIENT_ID")
                and _cfg("AZURE_KEYVAULT_CLIENT_SECRET") and _cfg("AZURE_KEYVAULT_URL"))


def _get_token() -> Optional[str]:
    tenant = _cfg("AZURE_TENANT_ID")
    client_id = _cfg("AZURE_KEYVAULT_CLIENT_ID")
    client_secret = _cfg("AZURE_KEYVAULT_CLIENT_SECRET")
    authority = _cfg("AZURE_AUTHORITY") or "login.microsoftonline.com"
    scope = _cfg("AZURE_KEYVAULT_SCOPE") or "https://vault.azure.net"
    if not all([tenant, client_id, client_secret]):
        return None

    cache_key = (tenant, client_id, scope)
    cached = _token_cache.get(cache_key)
    if cached and cached[1] - 60 > time.time():
        return cached[0]

    resp = httpx.post(
        f"https://{authority}/{tenant}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": f"{scope}/.default",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15.0,
    )
    resp.raise_for_status()
    body = resp.json()
    token = body["access_token"]
    _token_cache[cache_key] = (token, time.time() + int(body.get("expires_in", 3600)))
    return token


def _vault_url() -> str:
    return (_cfg("AZURE_KEYVAULT_URL") or "").rstrip("/")


def _api_version() -> str:
    return _cfg("AZURE_KEYVAULT_API_VERSION") or "7.4"


def encrypt(plaintext: str) -> str:
    """Encrypt with the configured Key Vault key (RSA-OAEP-256). Returns the
    base64url ciphertext. Suitable for small values (a wrapped DEK)."""
    token = _get_token()
    key_name = _cfg("AZURE_KEYVAULT_KEY")
    if not token or not key_name:
        raise RuntimeError("Azure Key Vault key crypto not configured")
    url = f"{_vault_url()}/keys/{key_name}/encrypt?api-version={_api_version()}"
    resp = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"alg": "RSA-OAEP-256", "value": _b64url_nopad(plaintext.encode("utf-8"))},
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()["value"]


def decrypt(ciphertext_b64url: str) -> str:
    token = _get_token()
    key_name = _cfg("AZURE_KEYVAULT_KEY")
    if not token or not key_name:
        raise RuntimeError("Azure Key Vault key crypto not configured")
    url = f"{_vault_url()}/keys/{key_name}/decrypt?api-version={_api_version()}"
    resp = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"alg": "RSA-OAEP-256", "value": ciphertext_b64url},
        timeout=15.0,
    )
    resp.raise_for_status()
    return _b64url_decode(resp.json()["value"]).decode("utf-8")
