"""Leader election for periodic work.

The background loops (telemetry polling, alert evaluation, backups, uptime
sampling) are started by every process that boots the app. With one worker that
is exactly right. With two, everything fires twice: doubled polling load on
every town, duplicate backups, duplicate uptime samples skewing the SLA figures.

A loop therefore takes a short lease before each pass and renews it while it
holds it. If the holder dies, the lease expires and another process takes over
within one TTL — no coordination service required, just the database both
processes already share.
"""

import logging
import os
import socket
from datetime import timedelta

from sqlalchemy.orm import Session

from orchestrator.models import ClusterLock, utcnow

logger = logging.getLogger(__name__)

# A lease must outlive one pass of the slowest loop, or the holder would lose it
# mid-run; it is renewed on every pass, so this only bounds failover time.
LEASE_SECONDS = 120


def instance_id() -> str:
    """Identifies this process in the lease table (host + pid)."""
    return f"{socket.gethostname()}:{os.getpid()}"


def acquire(db: Session, name: str, ttl: int = LEASE_SECONDS) -> bool:
    """Take or renew the named lease. True if this process now holds it.

    Contention is resolved by the database: the row is the lock, and a commit
    that violates the primary key means someone else won the race.
    """
    me = instance_id()
    now = utcnow()
    try:
        row = db.get(ClusterLock, name)
        if row is None:
            db.add(ClusterLock(name=name, owner=me, expires_at=now + timedelta(seconds=ttl)))
            db.commit()
            return True
        if row.owner == me or row.expires_at < now:
            if row.owner != me:
                logger.info("taking over %s lease from %s (expired)", name, row.owner)
            row.owner = me
            row.expires_at = now + timedelta(seconds=ttl)
            db.commit()
            return True
        db.rollback()
        return False
    except Exception:  # noqa: BLE001 — another process committed first
        db.rollback()
        return False


def release(db: Session, name: str) -> None:
    """Give up a lease on clean shutdown so failover is immediate."""
    try:
        row = db.get(ClusterLock, name)
        if row is not None and row.owner == instance_id():
            db.delete(row)
            db.commit()
    except Exception:  # noqa: BLE001 — shutdown must not raise
        db.rollback()
