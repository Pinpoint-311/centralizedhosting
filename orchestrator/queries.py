"""Small reusable read helpers shared across the API and services.

These queries were previously copy-pasted in half a dozen places (the "latest
release" lookup and the "latest snapshot per tenant" fold). Centralizing them
keeps the definition of "latest" in one spot.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orchestrator.models import Release, TelemetrySnapshot


def latest_release(db: Session) -> Release | None:
    """The most recently published release, or None when none exist."""
    return db.execute(
        select(Release).order_by(Release.published_at.desc())
    ).scalars().first()


def latest_snapshots(db: Session) -> dict[str, TelemetrySnapshot]:
    """The most recent telemetry snapshot per tenant, keyed by tenant id.

    Bounded: fetches only the newest row per tenant (~N rows) via a max()
    subquery, never the full history — so memory stays flat as snapshots
    accumulate from automatic polling. Portable across SQLite and Postgres.
    """
    newest = (
        select(
            TelemetrySnapshot.tenant_id.label("tid"),
            func.max(TelemetrySnapshot.collected_at).label("m"),
        )
        .group_by(TelemetrySnapshot.tenant_id)
        .subquery()
    )
    rows = db.execute(
        select(TelemetrySnapshot).join(
            newest,
            (TelemetrySnapshot.tenant_id == newest.c.tid)
            & (TelemetrySnapshot.collected_at == newest.c.m),
        )
    ).scalars().all()
    # If two snapshots share the exact newest timestamp, keep one deterministically.
    return {s.tenant_id: s for s in rows}


def prune_old_snapshots(db: Session, keep_days: int) -> int:
    """Delete telemetry snapshots older than ``keep_days``, except always keep
    each tenant's most recent one so status never goes blank. Keeps the table
    (and every scan over it) small under continuous polling. Returns rows deleted."""
    from datetime import timedelta

    from orchestrator.models import utcnow

    if keep_days <= 0:
        return 0
    cutoff = utcnow() - timedelta(days=keep_days)
    keep_ids = {s.id for s in latest_snapshots(db).values()}
    stale = db.execute(
        select(TelemetrySnapshot.id).where(TelemetrySnapshot.collected_at < cutoff)
    ).scalars().all()
    to_delete = [sid for sid in stale if sid not in keep_ids]
    if not to_delete:
        return 0
    for sid in to_delete:
        obj = db.get(TelemetrySnapshot, sid)
        if obj is not None:
            db.delete(obj)
    return len(to_delete)
