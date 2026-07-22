"""Town database backups — uniform with the Pinpoint 311 app's backup_service.

Same method and same env-var setup as the app:

  ``pg_dump -Fc`` (custom format)  →  ``gpg --symmetric --cipher-algo AES256``
  (passphrase = ``BACKUP_ENCRYPTION_KEY``)  →  upload to S3-compatible storage.

Configuration uses the SAME names as the app:
  BACKUP_S3_BUCKET, BACKUP_S3_ACCESS_KEY, BACKUP_S3_SECRET_KEY,
  BACKUP_ENCRYPTION_KEY (required); BACKUP_S3_ENDPOINT, BACKUP_S3_REGION
  (default us-ashburn-1), BACKUP_PREFIX ("db_backup_"), BACKUP_EXTENSION
  (".sql.gpg"). Restore mirrors the app: gpg --decrypt | pg_restore --clean.

In managed hosting the app's own backups are disabled (the state runs DR), so
the panel takes them for every town. When APPLY_STACKS is false (dev/CI) or S3
isn't configured, a backup is recorded as ``planned`` rather than executed —
the same seam the provisioner uses — so the control plane is fully testable.
"""

import logging
import os
import subprocess

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator import audit
from orchestrator.config import settings
from orchestrator.models import BackupRecord, Tenant, TenantStatus, utcnow

logger = logging.getLogger(__name__)

BACKUP_PREFIX = os.getenv("BACKUP_PREFIX", "db_backup_")
BACKUP_EXTENSION = os.getenv("BACKUP_EXTENSION", ".sql.gpg")


def _cfg(key: str, default: str | None = None) -> str | None:
    return os.getenv(key, default)


def s3_configured() -> bool:
    return bool(
        _cfg("BACKUP_S3_BUCKET")
        and _cfg("BACKUP_S3_ACCESS_KEY")
        and _cfg("BACKUP_S3_SECRET_KEY")
        and _cfg("BACKUP_ENCRYPTION_KEY")
    )


def _timestamp() -> str:
    return utcnow().strftime("%Y%m%d_%H%M%S")


def _object_key(tenant: Tenant, ts: str) -> str:
    return f"{BACKUP_PREFIX}{tenant.slug}_{ts}{BACKUP_EXTENSION}"


def _s3_client():
    import boto3

    kwargs = {
        "aws_access_key_id": _cfg("BACKUP_S3_ACCESS_KEY"),
        "aws_secret_access_key": _cfg("BACKUP_S3_SECRET_KEY"),
        "region_name": _cfg("BACKUP_S3_REGION", "us-ashburn-1"),
    }
    endpoint = _cfg("BACKUP_S3_ENDPOINT")
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.client("s3", **kwargs)


def _dump_encrypt_upload(tenant: Tenant, key: str) -> int:
    """pg_dump -Fc the town DB → gpg AES256 → S3. Returns bytes uploaded. Only
    reached when APPLY_STACKS is true and S3 is configured."""
    container = f"pp311-{tenant.slug}-db-1"
    db_user = f"pp311_{tenant.slug}".replace("-", "_")[:63]
    db_name = tenant.db_name or db_user

    dump = subprocess.run(
        ["docker", "exec", container, "pg_dump", "-Fc", "-U", db_user, db_name],
        capture_output=True, timeout=1800,
    )
    if dump.returncode != 0:
        raise RuntimeError(f"pg_dump failed for {tenant.slug}: {dump.stderr.decode()[-800:]}")

    enc = subprocess.run(
        ["gpg", "--batch", "--yes", "--symmetric", "--cipher-algo", "AES256",
         "--passphrase", _cfg("BACKUP_ENCRYPTION_KEY"), "-o", "-"],
        input=dump.stdout, capture_output=True, timeout=600,
    )
    if enc.returncode != 0:
        raise RuntimeError(f"gpg encrypt failed for {tenant.slug}: {enc.stderr.decode()[-800:]}")

    _s3_client().put_object(Bucket=_cfg("BACKUP_S3_BUCKET"), Key=key, Body=enc.stdout)
    return len(enc.stdout)


def run_base_backup(db: Session, tenant: Tenant, actor: str = "auto-backup") -> BackupRecord:
    """Take (or, without infra/S3, plan) one encrypted backup and catalog it."""
    ts = _timestamp()
    key = _object_key(tenant, ts)
    bucket = _cfg("BACKUP_S3_BUCKET") or "(unconfigured)"
    rec = BackupRecord(tenant_id=tenant.id, kind="dump", path=f"s3://{bucket}/{key}")

    if not settings.apply_stacks or not s3_configured():
        rec.status = "planned"
        why = "APPLY_STACKS=false" if not settings.apply_stacks else "BACKUP_S3_* not configured"
        rec.detail = f"{why} — pg_dump+gpg+S3 backup recorded as intent only"
    else:
        try:
            rec.size_bytes = _dump_encrypt_upload(tenant, key)
            rec.status = "completed"
            rec.detail = "pg_dump -Fc | gpg AES256 → S3"
        except Exception as exc:  # noqa: BLE001
            rec.status = "failed"
            rec.detail = str(exc)[:1000]
            logger.exception("backup failed for %s", tenant.slug)

    db.add(rec)
    audit.record(db, actor, "tenant.backup", tenant.id, kind="dump", status=rec.status)
    pruned = prune_old(db, tenant)
    db.commit()
    if pruned:
        logger.info("pruned %d expired backups for %s", pruned, tenant.slug)
    return rec


def prune_old(db: Session, tenant: Tenant) -> int:
    """Delete catalog rows (and their S3 objects) older than the retention
    window, always keeping the most recent completed backup."""
    cutoff = utcnow().timestamp() - settings.backup_retention_days * 86400
    rows = db.execute(
        select(BackupRecord)
        .where(BackupRecord.tenant_id == tenant.id)
        .order_by(BackupRecord.created_at.desc())
    ).scalars().all()

    client = None
    if settings.apply_stacks and s3_configured():
        try:
            client = _s3_client()
        except Exception:  # noqa: BLE001
            client = None

    kept_latest = False
    removed = 0
    for row in rows:
        if not kept_latest and row.status == "completed":
            kept_latest = True
            continue
        if row.created_at.timestamp() >= cutoff:
            continue
        if client and row.status == "completed" and row.path and row.path.startswith("s3://"):
            try:
                _, _, rest = row.path.partition("s3://")
                bucket, _, obj = rest.partition("/")
                client.delete_object(Bucket=bucket, Key=obj)
            except Exception:  # noqa: BLE001
                logger.warning("could not delete S3 object %s", row.path)
        db.delete(row)
        removed += 1
    return removed


def list_backups(db: Session, tenant_id: str) -> list[BackupRecord]:
    return db.execute(
        select(BackupRecord)
        .where(BackupRecord.tenant_id == tenant_id)
        .order_by(BackupRecord.created_at.desc())
        .limit(200)
    ).scalars().all()


def backup_all(db: Session, actor: str = "auto-backup") -> dict:
    """Back up every active town (background loop entrypoint)."""
    tenants = db.execute(
        select(Tenant).where(Tenant.status == TenantStatus.ACTIVE)
    ).scalars().all()
    done = 0
    for t in tenants:
        run_base_backup(db, t, actor)
        done += 1
    return {"backed_up": done}
