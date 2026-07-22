"""At-rest encryption facade for the panel — uniform with the Pinpoint 311 app.

This mirrors ``app/core/encryption.py`` in the app so the two systems are set up
and operated identically:

- Brokered/shared secrets are envelope-encrypted (see ``pii_crypto``): an
  AES-256-GCM data key (DEK) encrypts the value locally, and the DEK is wrapped
  by the configured cloud KMS — Google Cloud KMS (default), AWS KMS, or Azure
  Key Vault — or by a ``PANEL_SECRET_KEY``-derived key when no cloud KMS is
  configured. The wrapped DEK is cached, so the KMS is hit about once/process.
- The KMS is selected with ``KMS_PROVIDER`` (``google``|``azure``|``aws``) and
  configured with the SAME env vars as the app: ``GOOGLE_CLOUD_PROJECT``,
  ``KMS_LOCATION``, ``KMS_KEY_RING``, ``KMS_KEY_ID``; ``AWS_KMS_KEY_ID`` /
  ``AWS_REGION``; ``AZURE_KEYVAULT_URL`` / ``AZURE_KEYVAULT_KEY`` / ``AZURE_*``.
- ``REQUIRE_KMS`` makes envelope wrapping fail closed rather than silently
  downgrade to the local key.

Tokens are self-describing: the current scheme is ``pii2:``. Legacy Azure
per-field (``akv:``) and the panel's earlier versioned-Fernet (``v<n>:``) values
remain readable (see ``security.decrypt_value``).
"""

import base64
import hashlib
import logging
import os
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# Ciphertext prefixes (kept identical to the app).
ENCRYPTED_PREFIX = "gAAAA"        # Fernet tokens always start with this
KMS_ENCRYPTED_PREFIX = "kms:"     # Google KMS per-field (legacy in the app)
AZURE_ENCRYPTED_PREFIX = "akv:"   # Azure Key Vault per-field (legacy)
PII_V2_PREFIX = "pii2:"           # Envelope-encrypted (AES-256-GCM + KMS-wrapped DEK)


def _kms_provider() -> str:
    """Which KMS backend wraps the DEK: 'google' (default), 'azure', or 'aws'."""
    return (os.getenv("KMS_PROVIDER") or _get_config_sync("KMS_PROVIDER") or "google").strip().lower()


def _get_config_sync(key_name: str) -> Optional[str]:
    """Resolve a KMS/config value. The panel is env-configured (the app also
    reads a DB fallback; the panel keeps it env-only), so this is os.getenv."""
    return os.getenv(key_name)


def _kms_required() -> bool:
    """When REQUIRE_KMS is set, secret encryption must wrap the DEK with a real
    cloud KMS — any fallback to the local PANEL_SECRET_KEY-derived key raises
    instead of silently downgrading."""
    return os.getenv("REQUIRE_KMS", "").strip().lower() in ("1", "true", "yes", "on")


# --- local Fernet (legacy + no-KMS config path) ------------------------------

def _derive_key(secret_key: str) -> bytes:
    digest = hashlib.sha256(secret_key.encode()).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    from orchestrator.config import settings

    return Fernet(_derive_key(settings.panel_secret_key))


def encrypt(plaintext: str) -> str:
    """Fernet-encrypt (legacy/config path)."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def is_encrypted(value: Optional[str]) -> bool:
    if not value:
        return False
    return value.startswith((ENCRYPTED_PREFIX, KMS_ENCRYPTED_PREFIX,
                             AZURE_ENCRYPTED_PREFIX, PII_V2_PREFIX))


# --- Google Cloud KMS (DEK wrapping) -----------------------------------------

_kms_client = None
_kms_key_name = None


def _is_kms_available() -> bool:
    """Google Cloud KMS is available when a project is configured."""
    return bool(_get_config_sync("GOOGLE_CLOUD_PROJECT"))


def _get_kms_key_name() -> Optional[str]:
    """Assemble the Google KMS key resource name — identical shape to the app."""
    global _kms_key_name
    if _kms_key_name:
        return _kms_key_name
    project = _get_config_sync("GOOGLE_CLOUD_PROJECT")
    if not project:
        return None
    location = _get_config_sync("KMS_LOCATION") or "us-central1"
    key_ring = _get_config_sync("KMS_KEY_RING") or "pinpoint311-keyring"
    key_id = _get_config_sync("KMS_KEY_ID") or "pii-encryption-key"
    _kms_key_name = f"projects/{project}/locations/{location}/keyRings/{key_ring}/cryptoKeys/{key_id}"
    return _kms_key_name


def _get_kms_client():
    """Cached Google KMS client. Credentials come from GCP_SERVICE_ACCOUNT_JSON
    (a service-account JSON string) if set, else application-default creds
    (GOOGLE_APPLICATION_CREDENTIALS)."""
    global _kms_client
    if _kms_client:
        return _kms_client
    try:
        from google.cloud import kms
        sa_json = _get_config_sync("GCP_SERVICE_ACCOUNT_JSON")
        if sa_json:
            import json
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_info(json.loads(sa_json))
            _kms_client = kms.KeyManagementServiceClient(credentials=creds)
        else:
            _kms_client = kms.KeyManagementServiceClient()
        return _kms_client
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to initialize Google KMS client: {e}")
        return None


def active_backend() -> str:
    """Which key manager wraps the current DEK: 'google'|'azure'|'aws'|'local'.
    Surfaced by /api/whoami so operators can confirm HSM-backed wrapping."""
    from orchestrator import pii_crypto

    return pii_crypto.active_backend()
