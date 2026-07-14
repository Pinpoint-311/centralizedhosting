"""Small reusable read helpers shared across the API and services.

These queries were previously copy-pasted in half a dozen places (the "latest
release" lookup and the "latest snapshot per tenant" fold). Centralizing them
keeps the definition of "latest" in one spot.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.models import Release, TelemetrySnapshot


def latest_release(db: Session) -> Release | None:
    """The most recently published release, or None when none exist."""
    return db.execute(
        select(Release).order_by(Release.published_at.desc())
    ).scalars().first()


def latest_snapshots(db: Session) -> dict[str, TelemetrySnapshot]:
    """The most recent telemetry snapshot per tenant, keyed by tenant id."""
    latest: dict[str, TelemetrySnapshot] = {}
    for snap in db.execute(
        select(TelemetrySnapshot).order_by(TelemetrySnapshot.collected_at)
    ).scalars():
        latest[snap.tenant_id] = snap
    return latest
