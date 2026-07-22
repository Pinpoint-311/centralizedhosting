"""Point-in-time-recovery (PITR) backups for town databases.

Two layers give true PITR:

1. **Continuous WAL archiving** — enabled in the town's Postgres stack when
   ``BACKUPS_ENABLED`` (see the ``pitr`` block in the compose template). Every
   committed WAL segment is archived to the town's ``/backups`` volume, so the
   database can be replayed forward to any moment between base snapshots.
2. **Base snapshots** — the panel periodically takes a consistent base backup
   (``pg_basebackup``) of each active town and prunes to the retention window.
   This module is that catalog + driver; ``BackupRecord`` rows track each
   artifact's location, size, and status.

When ``APPLY_STACKS`` is false (dev/CI, no Docker), a base backup is *recorded
as planned* rather than executed — the same seam pattern the provisioner uses —
so the control-plane logic and API are fully exercised without real infra.
"""

import logging
import subprocess
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator import audit
from orchestrator.config import settings
from orchestrator.models import BackupRecord, Tenant, TenantStatus, utcnow

logger = logging.getLogger(__name__)


def tenant_backup_dir(tenant: Tenant) -> Path:
    return settings.backup_root / tenant.slug


def _timestamp() -> str:
    return utcnow().strftime("%Y%m%dT%H%M%SZ")


def _run_base_backup(tenant: Tenant, dest: Path) -> int:
    """`pg_basebackup` the town's DB container to a gzipped tar; return bytes
    written. Only reached when APPLY_STACKS=true."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    container = f"pp311-{tenant.slug}-db-1"
    db_user = f"pp311_{tenant.slug}".replace("-", "_")[:63]
    with dest.open("wb") as fh:
        result = subprocess.run(
            ["docker", "exec", container, "pg_basebackup",
             "-U", db_user, "-D", "-", "-Ft", "-z", "-X", "fetch"],
            stdout=fh, stderr=subprocess.PIPE, timeout=1800,
        )
    if result.returncode != 0:
        raise RuntimeError(
            f"pg_basebackup failed for {tenant.slug}: {result.stderr.decode()[-1000:]}"
        )
    return dest.stat().st_size if dest.exists() else 0


def run_base_backup(db: Session, tenant: Tenant, actor: str = "auto-backup") -> BackupRecord:
    """Take (or, without apply, plan) one base snapshot and catalog it."""
    ts = _timestamp()
    dest = tenant_backup_dir(tenant) / f"base-{ts}.tar.gz"
    rec = BackupRecord(tenant_id=tenant.id, kind="base", path=str(dest))

    if not settings.apply_stacks:
        rec.status = "planned"
        rec.detail = "APPLY_STACKS=false — base snapshot recorded as intent only"
    else:
        try:
            rec.size_bytes = _run_base_backup(tenant, dest)
            rec.status = "completed"
            rec.detail = "pg_basebackup (tar.gz, WAL fetched) — PITR base"
        except Exception as exc:  # noqa: BLE001
            rec.status = "failed"
            rec.detail = str(exc)[:1000]
            logger.exception("base backup failed for %s", tenant.slug)

    db.add(rec)
    audit.record(db, actor, "tenant.backup", tenant.id, kind="base", status=rec.status)
    pruned = prune_old(db, tenant)
    db.commit()
    if pruned:
        logger.info("pruned %d expired backups for %s", pruned, tenant.slug)
    return rec


def prune_old(db: Session, tenant: Tenant) -> int:
    """Delete catalog rows (and their files) older than the retention window,
    always keeping the most recent completed snapshot."""
    cutoff = utcnow().timestamp() - settings.backup_retention_days * 86400
    rows = db.execute(
        select(BackupRecord)
        .where(BackupRecord.tenant_id == tenant.id)
        .order_by(BackupRecord.created_at.desc())
    ).scalars().all()

    kept_latest = False
    removed = 0
    for row in rows:
        # Always keep the newest completed snapshot regardless of age.
        if not kept_latest and row.status == "completed":
            kept_latest = True
            continue
        if row.created_at.timestamp() >= cutoff:
            continue
        if row.path:
            Path(row.path).unlink(missing_ok=True)
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
    """Base-backup every active town (background loop entrypoint)."""
    tenants = db.execute(
        select(Tenant).where(Tenant.status == TenantStatus.ACTIVE)
    ).scalars().all()
    done = 0
    for t in tenants:
        run_base_backup(db, t, actor)
        done += 1
    return {"backed_up": done}
