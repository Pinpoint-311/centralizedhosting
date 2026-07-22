"""Lightweight background polling: bounded 'latest snapshot' reads + pruning."""

from datetime import timedelta

from sqlalchemy import select

from orchestrator.models import TelemetrySnapshot, utcnow
from orchestrator.queries import latest_snapshots, prune_old_snapshots
from tests.conftest import make_tenant


def _snap(tid, hours_ago=0, days_ago=0, **kw):
    return TelemetrySnapshot(
        tenant_id=tid,
        reachable=kw.pop("reachable", True),
        collected_at=utcnow() - timedelta(hours=hours_ago, days=days_ago),
        payload=kw.pop("payload", {}),
    )


def test_latest_snapshots_returns_newest_per_tenant(client, db):
    t = make_tenant(client, slug="polltown", name="Poll Town")
    db.add(_snap(t["id"], hours_ago=2, reachable=False, payload={"version": "1.0.0"}))
    db.add(_snap(t["id"], hours_ago=0, reachable=True, payload={"version": "1.1.0"}))
    db.commit()

    latest = latest_snapshots(db)
    assert latest[t["id"]].payload["version"] == "1.1.0"
    assert latest[t["id"]].reachable is True


def test_prune_removes_old_but_keeps_latest(client, db):
    t = make_tenant(client, slug="prunetown", name="Prune Town")
    db.add_all([
        _snap(t["id"], days_ago=60),
        _snap(t["id"], days_ago=45),
        _snap(t["id"], days_ago=0),
    ])
    db.commit()

    deleted = prune_old_snapshots(db, keep_days=30)
    db.commit()

    remaining = db.execute(
        select(TelemetrySnapshot).where(TelemetrySnapshot.tenant_id == t["id"])
    ).scalars().all()
    assert deleted == 2
    assert len(remaining) == 1  # the recent one survives


def test_prune_never_empties_a_tenant(client, db):
    """A tenant whose only snapshot is old must keep it — status never blanks."""
    t = make_tenant(client, slug="staletown", name="Stale Town")
    db.add(_snap(t["id"], days_ago=90))
    db.commit()

    prune_old_snapshots(db, keep_days=30)
    db.commit()

    remaining = db.execute(
        select(TelemetrySnapshot).where(TelemetrySnapshot.tenant_id == t["id"])
    ).scalars().all()
    assert len(remaining) == 1


def test_prune_disabled_when_zero(client, db):
    t = make_tenant(client, slug="keepall", name="Keep All")
    db.add_all([_snap(t["id"], days_ago=200), _snap(t["id"], days_ago=0)])
    db.commit()
    assert prune_old_snapshots(db, keep_days=0) == 0
