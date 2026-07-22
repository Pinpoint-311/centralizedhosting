"""Panel-secret key management.

The panel encrypts brokered/shared credentials at rest with a Fernet data key
(DEK). Where that DEK comes from is pluggable:

- ``local`` — derive the DEK from PANEL_SECRET_KEY (dev / single-host).
- ``kms``   — the DEK is generated once as 32 random bytes and stored **wrapped**
              by a FedRAMP/StateRAMP KMS/HSM (GCP Cloud KMS, AWS KMS, or a
              software-held ``local-hsm`` KEK for CI/self-host). Only the wrapped
              form is persisted (``WrappedKey``); it's unwrapped via the KMS on
              first use and cached in memory. This is the government-correct
              posture — see ``orchestrator/kms.py`` for the wrap/unwrap backends.

Rotation: ``PANEL_KEK_VERSION`` selects the active key version. Bumping it makes
the next encrypt mint (and, for kms, wrap+store) a fresh DEK for that version;
``reencrypt_all_secrets`` then re-encrypts every stored secret from the old DEK
to the new one, so a compromised or aged key can be retired without data loss —
while older ciphertext still decrypts under its original version.
"""

import base64
import hashlib
import secrets as pysecrets

from cryptography.fernet import Fernet

from orchestrator.config import settings


def _fernet_from_material(material: bytes) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(material).digest()))


def _fernet_from_dek(dek: bytes) -> Fernet:
    """Wrap a raw 32-byte DEK as a Fernet key (no re-hashing — the KMS DEK is
    already cryptographically random key material)."""
    return Fernet(base64.urlsafe_b64encode(dek))


def _local_dek(version: int) -> bytes:
    # v1 == the historical material (sha256 of PANEL_SECRET_KEY) so already-
    # stored ciphertext keeps decrypting; later versions mix in the version so
    # rotation yields a distinct key.
    if version <= 1:
        return settings.panel_secret_key.encode()
    return f"{settings.panel_secret_key}:v{version}".encode()


# --- KMS-wrapped DEK storage (government production) --------------------------
# The plaintext DEK is generated once per version, wrapped by the KMS/HSM, and
# only the wrapped form is persisted. It's unwrapped on first use and cached in
# memory for the process lifetime.

_dek_cache: dict[int, bytes] = {}


def reset_cache() -> None:
    """Drop the in-memory unwrapped-DEK cache (used after rotation/tests)."""
    _dek_cache.clear()


def _kms_dek(version: int) -> bytes:
    cached = _dek_cache.get(version)
    if cached is not None:
        return cached

    from orchestrator import kms
    from orchestrator.db import SessionLocal
    from orchestrator.models import WrappedKey

    with SessionLocal() as db:
        row = db.get(WrappedKey, version)
        if row is None:
            # First use of this version: mint a random DEK, wrap it with the KMS
            # KEK, and persist only the wrapped form.
            dek = pysecrets.token_bytes(32)
            wrapped = kms.wrap(dek)
            db.add(
                WrappedKey(
                    version=version,
                    wrapped_dek=base64.b64encode(wrapped).decode(),
                    backend=settings.kms_backend,
                    kek_resource=settings.kms_key_resource or None,
                )
            )
            db.commit()
        else:
            dek = kms.unwrap(base64.b64decode(row.wrapped_dek))

    _dek_cache[version] = dek
    return dek


def data_key(version: int | None = None) -> Fernet:
    """The Fernet DEK for the given key version (default: active version)."""
    version = settings.panel_kek_version if version is None else version
    if settings.key_provider == "local":
        return _fernet_from_material(_local_dek(version))
    if settings.key_provider == "kms":
        return _fernet_from_dek(_kms_dek(version))
    raise ValueError(f"Unknown KEY_PROVIDER: {settings.key_provider}")


def active() -> Fernet:
    return data_key()


def for_version(version: int) -> Fernet:
    return data_key(version)
