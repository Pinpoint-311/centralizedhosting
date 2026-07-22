"""Envelope encryption for secrets at rest — ported from the Pinpoint 311 app
(``app/core/pii_crypto.py``) so the panel and the app encrypt identically.

  * A 256-bit Data Encryption Key (DEK) encrypts each value locally with
    AES-256-GCM (authenticated encryption).
  * The DEK is wrapped (encrypted) by the configured key manager — Google Cloud
    KMS, AWS KMS, Azure Key Vault, or, when no cloud KMS is configured, a
    Key-Encryption-Key derived from ``PANEL_SECRET_KEY`` via HKDF.
  * The wrapped DEK is cached in-process, so the KMS is contacted about once per
    process (and again only when the DEK rotates) rather than per value.

Ciphertext format (self-describing, versioned) — identical to the app:

    pii2:<wrapped_dek_b64>:<nonce_b64>:<ciphertext_b64>

The wrapped DEK's first byte tags the backend that can unwrap it ('g' Google,
'a' Azure, 'w' AWS, 'l' local).
"""

import base64
import logging
import os
import threading
from collections import OrderedDict
from typing import Optional, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

logger = logging.getLogger(__name__)

PII_V2_PREFIX = "pii2:"

# Backend tags stored as the first byte of a wrapped DEK.
_WRAP_GOOGLE = b"g"
_WRAP_AZURE = b"a"
_WRAP_AWS = b"w"
_WRAP_LOCAL = b"l"

# AES-GCM associated data — binds ciphertext to its purpose.
_AAD_PII = b"pinpoint-pii-v2"
_AAD_DEK = b"pinpoint-dek-v2"

_lock = threading.Lock()
_active: Optional[Tuple[str, bytes]] = None            # (wrapped_dek_b64, dek_bytes)
_unwrap_cache: "OrderedDict[str, bytes]" = OrderedDict()  # wrapped_dek_b64 -> dek
_UNWRAP_CACHE_MAX = 32

_plain_cache: "OrderedDict[str, str]" = OrderedDict()
_PLAIN_CACHE_MAX = 4096


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s)


def _decrypt_cache_enabled() -> bool:
    return (os.getenv("PII_DECRYPT_CACHE") or "on").strip().lower() not in ("off", "0", "false", "no")


# --------------------------------------------------------------------------
# Key-Encryption-Key (KEK) backends
# --------------------------------------------------------------------------

def _local_kek() -> bytes:
    """32-byte KEK derived from PANEL_SECRET_KEY via HKDF-SHA256. Wraps the DEK
    when no cloud KMS is configured (dev / self-hosted without an HSM)."""
    from orchestrator.config import settings

    secret = settings.panel_secret_key.encode("utf-8")
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32,
                salt=b"pinpoint311-pii-kek", info=b"dek-wrap")
    return hkdf.derive(secret)


def _wrap_dek(dek: bytes) -> bytes:
    """Wrap the DEK with the configured key manager. First byte tags the backend."""
    from orchestrator.encryption import _kms_provider, _is_kms_available, _kms_required

    provider = _kms_provider()

    if provider == "azure":
        from orchestrator import azure_keyvault
        if azure_keyvault.is_configured():
            return _WRAP_AZURE + azure_keyvault.encrypt(_b64(dek)).encode("ascii")
        if _kms_required():
            raise RuntimeError("REQUIRE_KMS is set but Azure Key Vault is not configured.")
        return _WRAP_LOCAL + _local_wrap(dek)

    if provider == "aws":
        from orchestrator import aws_kms
        if aws_kms.is_configured():
            return _WRAP_AWS + aws_kms.encrypt(dek)
        if _kms_required():
            raise RuntimeError("REQUIRE_KMS is set but AWS KMS is not configured.")
        return _WRAP_LOCAL + _local_wrap(dek)

    if provider == "google" and _is_kms_available():
        from orchestrator.encryption import _get_kms_client, _get_kms_key_name
        client, key_name = _get_kms_client(), _get_kms_key_name()
        if client and key_name:
            resp = client.encrypt(request={"name": key_name, "plaintext": dek})
            return _WRAP_GOOGLE + resp.ciphertext
        if _kms_required():
            raise RuntimeError("REQUIRE_KMS is set but the Google KMS client/key is unavailable.")
        return _WRAP_LOCAL + _local_wrap(dek)

    if _kms_required():
        raise RuntimeError(
            "REQUIRE_KMS is set but no cloud KMS is configured — refusing to "
            "wrap the data key with a local PANEL_SECRET_KEY-derived key."
        )
    return _WRAP_LOCAL + _local_wrap(dek)


def _unwrap_dek(wrapped: bytes) -> bytes:
    tag, payload = wrapped[:1], wrapped[1:]
    if tag == _WRAP_LOCAL:
        return _local_unwrap(payload)
    if tag == _WRAP_GOOGLE:
        from orchestrator.encryption import _get_kms_client, _get_kms_key_name
        client, key_name = _get_kms_client(), _get_kms_key_name()
        if not client or not key_name:
            raise RuntimeError("Google KMS unavailable to unwrap the data key.")
        resp = client.decrypt(request={"name": key_name, "ciphertext": payload})
        return resp.plaintext
    if tag == _WRAP_AZURE:
        from orchestrator import azure_keyvault
        return _unb64(azure_keyvault.decrypt(payload.decode("ascii")))
    if tag == _WRAP_AWS:
        from orchestrator import aws_kms
        return aws_kms.decrypt(payload)
    raise ValueError(f"Unknown DEK wrap tag: {tag!r}")


def _local_wrap(dek: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(_local_kek()).encrypt(nonce, dek, _AAD_DEK)


def _local_unwrap(payload: bytes) -> bytes:
    nonce, ct = payload[:12], payload[12:]
    return AESGCM(_local_kek()).decrypt(nonce, ct, _AAD_DEK)


# --------------------------------------------------------------------------
# Active DEK (cached) + unwrap cache
# --------------------------------------------------------------------------

def _get_active_dek() -> Tuple[str, bytes]:
    global _active
    if _active is not None:
        return _active
    with _lock:
        if _active is None:
            dek = AESGCM.generate_key(bit_length=256)
            wrapped_b64 = _b64(_wrap_dek(dek))
            _unwrap_cache[wrapped_b64] = dek
            _active = (wrapped_b64, dek)
    return _active


def _dek_for(wrapped_b64: str) -> bytes:
    dek = _unwrap_cache.get(wrapped_b64)
    if dek is not None:
        _unwrap_cache.move_to_end(wrapped_b64)
        return dek
    with _lock:
        dek = _unwrap_cache.get(wrapped_b64)
        if dek is None:
            dek = _unwrap_dek(_unb64(wrapped_b64))
            _unwrap_cache[wrapped_b64] = dek
            while len(_unwrap_cache) > _UNWRAP_CACHE_MAX:
                _unwrap_cache.popitem(last=False)
    return dek


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def is_v2(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(PII_V2_PREFIX)


def encrypt(plaintext: str) -> str:
    """Envelope-encrypt a value. Returns a ``pii2:`` token."""
    wrapped_b64, dek = _get_active_dek()
    nonce = os.urandom(12)
    ct = AESGCM(dek).encrypt(nonce, plaintext.encode("utf-8"), _AAD_PII)
    return f"{PII_V2_PREFIX}{wrapped_b64}:{_b64(nonce)}:{_b64(ct)}"


def decrypt(token: str) -> str:
    """Decrypt a ``pii2:`` token. Raises on a malformed or tampered value."""
    if _decrypt_cache_enabled():
        cached = _plain_cache.get(token)
        if cached is not None:
            _plain_cache.move_to_end(token)
            return cached

    try:
        _, wrapped_b64, nonce_b64, ct_b64 = token.split(":", 3)
    except ValueError:
        raise ValueError("Malformed pii2 token")
    dek = _dek_for(wrapped_b64)
    plaintext = AESGCM(dek).decrypt(_unb64(nonce_b64), _unb64(ct_b64), _AAD_PII).decode("utf-8")

    if _decrypt_cache_enabled():
        _plain_cache[token] = plaintext
        _plain_cache.move_to_end(token)
        while len(_plain_cache) > _PLAIN_CACHE_MAX:
            _plain_cache.popitem(last=False)
    return plaintext


def active_backend() -> str:
    wrapped_b64, _ = _get_active_dek()
    tag = base64.b64decode(wrapped_b64)[:1]
    return {_WRAP_GOOGLE: "google", _WRAP_AZURE: "azure",
            _WRAP_AWS: "aws", _WRAP_LOCAL: "local"}.get(tag, "unknown")


def clear_caches() -> None:
    """Drop the active DEK and all caches — call after rotating the KMS key so
    new writes re-wrap and reads re-unwrap against the current key."""
    global _active
    with _lock:
        _active = None
        _unwrap_cache.clear()
        _plain_cache.clear()
