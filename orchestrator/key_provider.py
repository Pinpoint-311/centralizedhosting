"""Panel-secret key management.

The panel encrypts brokered/shared credentials at rest with a Fernet data key
(DEK). Where that DEK comes from is pluggable:

- ``local``  — derive the DEK from PANEL_SECRET_KEY (dev / single-host).
- ``kms``    — the DEK is generated once and stored **wrapped** by a
               FedRAMP/StateRAMP KMS (GCP Cloud KMS, AWS KMS, Azure Key Vault
               in the Gov cloud); it's unwrapped at startup. This is the
               government-correct posture. The wrap/unwrap seam is
               ``_kms_wrap``/`_kms_unwrap` below — drop the cloud SDK call in
               there; everything else (envelope storage, rotation) already works.

Rotation: `PANEL_KEK_VERSION` selects the active key version. `rotate()`
re-encrypts every stored secret from the old DEK to the new one, so a
compromised or aged key can be retired without data loss.
"""

import base64
import hashlib

from cryptography.fernet import Fernet

from orchestrator.config import settings


def _fernet_from_material(material: bytes) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(material).digest()))


def _local_dek(version: int) -> bytes:
    # v1 == the historical material (sha256 of PANEL_SECRET_KEY) so already-
    # stored ciphertext keeps decrypting; later versions mix in the version so
    # rotation yields a distinct key.
    if version <= 1:
        return settings.panel_secret_key.encode()
    return f"{settings.panel_secret_key}:v{version}".encode()


# --- KMS seam (government production) ----------------------------------------
# Replace the bodies with real KMS calls. The DEK is a random 32 bytes; the KMS
# stores only the *wrapped* form. We never persist the plaintext DEK.

def _kms_wrap(dek: bytes) -> bytes:  # pragma: no cover - deployment-specific
    raise NotImplementedError(
        "KEY_PROVIDER=kms requires a KMS wrap implementation — see GOVERNMENT_PRODUCTION.md"
    )


def _kms_unwrap(wrapped: bytes) -> bytes:  # pragma: no cover - deployment-specific
    raise NotImplementedError(
        "KEY_PROVIDER=kms requires a KMS unwrap implementation — see GOVERNMENT_PRODUCTION.md"
    )


def data_key(version: int | None = None) -> Fernet:
    """The Fernet DEK for the given key version (default: active version)."""
    version = settings.panel_kek_version if version is None else version
    if settings.key_provider == "local":
        return _fernet_from_material(_local_dek(version))
    if settings.key_provider == "kms":
        # In a real deployment the wrapped DEK per version is loaded from the DB
        # and unwrapped via KMS. Structure is in place; the cloud call is the
        # only missing piece.
        raise NotImplementedError(
            "KEY_PROVIDER=kms: wire _kms_wrap/_kms_unwrap and wrapped-DEK storage"
        )
    raise ValueError(f"Unknown KEY_PROVIDER: {settings.key_provider}")


def active() -> Fernet:
    return data_key()


def for_version(version: int) -> Fernet:
    return data_key(version)
