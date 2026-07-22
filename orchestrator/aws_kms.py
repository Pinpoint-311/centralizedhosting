"""AWS KMS key-wrapping (boto3) — ported from the app for uniform KMS setup.

Wraps only the 32-byte DEK (see pii_crypto), never the secret itself. Same env
vars as the app: AWS_KMS_KEY_ID, AWS_REGION, and the optional
AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN (else the default
credential chain / instance role)."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _cfg(key: str) -> Optional[str]:
    from orchestrator.encryption import _get_config_sync

    return _get_config_sync(key)


def is_configured() -> bool:
    return bool(_cfg("AWS_KMS_KEY_ID") and _cfg("AWS_REGION"))


def _client():
    try:
        import boto3
    except Exception as e:  # pragma: no cover
        logger.error(f"boto3 unavailable for AWS KMS: {e}")
        return None
    region = _cfg("AWS_REGION")
    if not region:
        return None
    kwargs = {"region_name": region}
    access_key = _cfg("AWS_ACCESS_KEY_ID")
    secret_key = _cfg("AWS_SECRET_ACCESS_KEY")
    if access_key and secret_key:
        kwargs["aws_access_key_id"] = access_key
        kwargs["aws_secret_access_key"] = secret_key
        session_token = _cfg("AWS_SESSION_TOKEN")
        if session_token:
            kwargs["aws_session_token"] = session_token
    try:
        return boto3.client("kms", **kwargs)
    except Exception as e:  # pragma: no cover
        logger.error(f"Could not build AWS KMS client: {e}")
        return None


def encrypt(dek: bytes) -> bytes:
    client = _client()
    key_id = _cfg("AWS_KMS_KEY_ID")
    if not client or not key_id:
        raise RuntimeError("AWS KMS not configured")
    return client.encrypt(KeyId=key_id, Plaintext=dek)["CiphertextBlob"]


def decrypt(blob: bytes) -> bytes:
    client = _client()
    key_id = _cfg("AWS_KMS_KEY_ID")
    if not client:
        raise RuntimeError("AWS KMS not configured")
    kwargs = {"CiphertextBlob": blob}
    if key_id:
        kwargs["KeyId"] = key_id
    return client.decrypt(**kwargs)["Plaintext"]
