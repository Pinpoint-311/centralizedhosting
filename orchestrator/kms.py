"""Cloud KMS / HSM backends for envelope-encrypting the panel's data key.

Envelope encryption: a random 32-byte data-encryption key (DEK) is generated
once, *wrapped* (encrypted) by a key-encryption key (KEK) that lives in a
KMS/HSM, and only the wrapped DEK is ever persisted (``WrappedKey`` table). At
use time the wrapped DEK is unwrapped by the KMS and turned into the Fernet key
that encrypts brokered secrets. The plaintext DEK never touches disk, and
destroying the KEK in the KMS crypto-shreds every secret wrapped under it.

Backends (``KMS_BACKEND``):

- ``local-hsm`` — the KEK is held in ``KMS_KEK_MATERIAL`` (env / mounted
  secret). Wrapping is AES-128-CBC+HMAC via Fernet. This is for dev/CI and
  self-hosted installs with no cloud dependency; it is still real envelope
  crypto (the DB holds only wrapped DEKs) but the KEK is software-held rather
  than in a hardware module.
- ``gcp`` — Google Cloud KMS / Cloud HSM (``google-cloud-kms``). Wrap/unwrap are
  KMS Encrypt/Decrypt calls on ``KMS_KEY_RESOURCE``.
- ``aws`` — AWS KMS / CloudHSM (``boto3``). Same, on the key ARN/id.

The cloud backends import their SDK lazily so the panel runs without them
installed; a missing SDK raises a clear ``KmsError`` only when that backend is
actually selected.
"""

import base64
import hashlib

from orchestrator.config import settings


class KmsError(RuntimeError):
    """Raised when a KMS wrap/unwrap cannot be performed."""


# --- local-hsm ---------------------------------------------------------------

def _local_kek_fernet():
    from cryptography.fernet import Fernet

    material = settings.kms_kek_material
    if not material:
        raise KmsError(
            "KMS_BACKEND=local-hsm requires KMS_KEK_MATERIAL (the wrapping key)."
        )
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest()))


def _local_wrap(dek: bytes) -> bytes:
    return _local_kek_fernet().encrypt(dek)


def _local_unwrap(wrapped: bytes) -> bytes:
    try:
        return _local_kek_fernet().decrypt(wrapped)
    except Exception as exc:  # noqa: BLE001
        raise KmsError(f"local-hsm unwrap failed: {exc}") from exc


# --- gcp ---------------------------------------------------------------------

def _gcp_client():  # pragma: no cover - requires cloud SDK + creds
    try:
        from google.cloud import kms
    except ImportError as exc:
        raise KmsError(
            "KMS_BACKEND=gcp requires google-cloud-kms (pip install google-cloud-kms)."
        ) from exc
    return kms.KeyManagementServiceClient()


def _gcp_wrap(dek: bytes) -> bytes:  # pragma: no cover - cloud path
    if not settings.kms_key_resource:
        raise KmsError("KMS_BACKEND=gcp requires KMS_KEY_RESOURCE (the cryptoKey name).")
    client = _gcp_client()
    resp = client.encrypt(request={"name": settings.kms_key_resource, "plaintext": dek})
    return resp.ciphertext


def _gcp_unwrap(wrapped: bytes) -> bytes:  # pragma: no cover - cloud path
    client = _gcp_client()
    resp = client.decrypt(request={"name": settings.kms_key_resource, "ciphertext": wrapped})
    return resp.plaintext


# --- aws ---------------------------------------------------------------------

def _aws_client():  # pragma: no cover - requires cloud SDK + creds
    try:
        import boto3
    except ImportError as exc:
        raise KmsError("KMS_BACKEND=aws requires boto3 (pip install boto3).") from exc
    return boto3.client("kms")


def _aws_wrap(dek: bytes) -> bytes:  # pragma: no cover - cloud path
    if not settings.kms_key_resource:
        raise KmsError("KMS_BACKEND=aws requires KMS_KEY_RESOURCE (the key ARN/id).")
    resp = _aws_client().encrypt(KeyId=settings.kms_key_resource, Plaintext=dek)
    return resp["CiphertextBlob"]


def _aws_unwrap(wrapped: bytes) -> bytes:  # pragma: no cover - cloud path
    resp = _aws_client().decrypt(
        CiphertextBlob=wrapped,
        **({"KeyId": settings.kms_key_resource} if settings.kms_key_resource else {}),
    )
    return resp["Plaintext"]


# --- dispatch ----------------------------------------------------------------

_BACKENDS = {
    "local-hsm": (_local_wrap, _local_unwrap),
    "gcp": (_gcp_wrap, _gcp_unwrap),
    "aws": (_aws_wrap, _aws_unwrap),
}


def wrap(dek: bytes) -> bytes:
    """Wrap a plaintext DEK with the configured KMS KEK."""
    try:
        fn = _BACKENDS[settings.kms_backend][0]
    except KeyError:
        raise KmsError(f"Unknown KMS_BACKEND: {settings.kms_backend!r}")
    return fn(dek)


def unwrap(wrapped: bytes) -> bytes:
    """Unwrap a KMS-wrapped DEK back to plaintext."""
    try:
        fn = _BACKENDS[settings.kms_backend][1]
    except KeyError:
        raise KmsError(f"Unknown KMS_BACKEND: {settings.kms_backend!r}")
    return fn(wrapped)
