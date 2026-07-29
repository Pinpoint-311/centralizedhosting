"""State that must survive more than one process.

The panel ships as a single uvicorn worker, so these were latent rather than
broken — but every one of them fails silently and intermittently the moment a
second worker or replica appears, which is the worst way to find out.
"""

from datetime import timedelta

from orchestrator import cluster
from orchestrator.models import ClusterLock, LoginState, utcnow
from tests.conftest import HEADERS


# --------------------------------------------------------------- login state

def test_login_state_round_trips_through_the_database(client, db):
    """/sso/login and /sso/callback can be served by different workers, so the
    state cannot live in process memory."""
    from orchestrator.api import auth_sso

    auth_sso._store_state(db, "state-abc", "nonce-xyz", "verifier-123")

    # A *different* session stands in for another worker.
    from orchestrator.db import SessionLocal

    with SessionLocal() as other:
        ctx = auth_sso._take_state(other, "state-abc")
    assert ctx == {"nonce": "nonce-xyz", "verifier": "verifier-123", "expired": False}


def test_login_state_is_single_use(client, db):
    from orchestrator.api import auth_sso

    auth_sso._store_state(db, "once", "n", "v")
    assert auth_sso._take_state(db, "once") is not None
    assert auth_sso._take_state(db, "once") is None  # replay refused


def test_expired_login_state_is_refused_and_reaped(client, db):
    from orchestrator.api import auth_sso

    db.add(LoginState(state="stale", nonce="n", code_verifier="v",
                      expires_at=utcnow() - timedelta(seconds=1)))
    db.commit()
    assert auth_sso._take_state(db, "stale") is None
    assert db.get(LoginState, "stale") is None  # consumed, not left to accumulate


def test_unknown_state_is_refused(client, db):
    from orchestrator.api import auth_sso

    assert auth_sso._take_state(db, "never-issued") is None


# ------------------------------------------------------------- leader election

def test_only_one_holder_at_a_time(client, db, monkeypatch):
    assert cluster.acquire(db, "demo_loop") is True

    # A second process (different instance id) must not get the lease.
    monkeypatch.setattr(cluster, "instance_id", lambda: "other-host:999")
    assert cluster.acquire(db, "demo_loop") is False


def test_holder_can_renew_its_own_lease(client, db):
    assert cluster.acquire(db, "renew_loop") is True
    assert cluster.acquire(db, "renew_loop") is True  # renewal, not contention


def test_an_expired_lease_is_taken_over(client, db, monkeypatch):
    """If the holder dies, the work must not stop forever."""
    assert cluster.acquire(db, "failover_loop") is True
    row = db.get(ClusterLock, "failover_loop")
    row.expires_at = utcnow() - timedelta(seconds=1)  # holder died
    db.commit()

    monkeypatch.setattr(cluster, "instance_id", lambda: "successor:1")
    assert cluster.acquire(db, "failover_loop") is True
    assert db.get(ClusterLock, "failover_loop").owner == "successor:1"


def test_release_hands_the_lease_back(client, db, monkeypatch):
    assert cluster.acquire(db, "release_loop") is True
    cluster.release(db, "release_loop")
    assert db.get(ClusterLock, "release_loop") is None

    monkeypatch.setattr(cluster, "instance_id", lambda: "next:2")
    assert cluster.acquire(db, "release_loop") is True  # immediate failover


def test_release_by_a_non_holder_is_a_no_op(client, db, monkeypatch):
    assert cluster.acquire(db, "guard_loop") is True
    monkeypatch.setattr(cluster, "instance_id", lambda: "intruder:3")
    cluster.release(db, "guard_loop")
    assert db.get(ClusterLock, "guard_loop") is not None  # still held by the owner
