"""Background execution for long-running orchestration.

Provisioning and rollouts shell out to ``docker compose`` with minute-scale
timeouts. Run inline they hold an HTTP request open for the whole run, so a
proxy or browser timeout drops the client mid-run — the work continues
server-side, but the operator is left staring at a failed request with no idea
whether their town was built. The job/step rows already existed to describe a
run; this makes them the actual interface: the request enqueues and returns
immediately, and the UI polls.

Concurrency is guarded by a database lease, not process memory, so two workers
cannot start the same town. The lease is renewed while the job runs and released
when it finishes; if the process dies mid-run it expires and the work becomes
claimable again rather than wedging that town forever.
"""

import logging
import threading

logger = logging.getLogger(__name__)

# Long enough that a slow compose pull doesn't lose the lease between renewals,
# short enough that a crashed worker frees the town quickly.
LEASE_SECONDS = 90
_RENEW_EVERY = 30

# In-process mirror of the held leases. Purely an optimisation so is_running()
# and wait() don't hit the database in a tight loop; the lease is the authority.
_lock = threading.Lock()
_inflight: set[str] = set()


def _lock_name(key: str) -> str:
    return f"job:{key}"


def is_running(key: str) -> bool:
    """True if THIS process is running the key. Cross-process callers should
    consult :func:`is_locked`, which reads the shared lease."""
    with _lock:
        return key in _inflight


def is_locked(key: str) -> bool:
    """True if any process holds the lease for this key."""
    from orchestrator.cluster import is_held
    from orchestrator.db import SessionLocal

    with SessionLocal() as db:
        return is_held(db, _lock_name(key))


def wait(key: str, timeout: float = 120.0, interval: float = 0.01) -> bool:
    """Block until this process finishes ``key``. False if it was still running
    when the timeout elapsed. For callers that need the result inline — tests,
    and any CLI that wants to report an outcome rather than a job id."""
    import time

    deadline = time.monotonic() + timeout
    while is_running(key) and time.monotonic() < deadline:
        time.sleep(interval)
    return not is_running(key)


def submit(key: str, fn, *args, **kwargs) -> bool:
    """Run ``fn`` on a background thread, at most once across the whole cluster.

    Returns False when another run holds the lease — the caller should tell the
    operator rather than starting a second concurrent run. ``fn`` opens its own
    database session: the request that submitted the work has already returned,
    so its session is gone.
    """
    from orchestrator import cluster
    from orchestrator.db import SessionLocal

    name = _lock_name(key)
    with SessionLocal() as db:
        if not cluster.acquire(db, name, ttl=LEASE_SECONDS):
            return False

    with _lock:
        _inflight.add(key)

    done = threading.Event()

    def _renew():
        # Hold the lease for as long as the work runs, so a slow provision
        # doesn't let another worker start a second one on top of it.
        while not done.wait(_RENEW_EVERY):
            try:
                with SessionLocal() as db:
                    cluster.acquire(db, name, ttl=LEASE_SECONDS)
            except Exception:  # noqa: BLE001 — a failed renewal must not kill the job
                logger.warning("could not renew lease for %s", key, exc_info=True)

    def _run():
        try:
            fn(*args, **kwargs)
        except Exception:  # noqa: BLE001 — a crashed job must not strand the lease
            logger.exception("background job %s failed", key)
        finally:
            done.set()
            try:
                with SessionLocal() as db:
                    cluster.release(db, name)
            except Exception:  # noqa: BLE001
                logger.warning("could not release lease for %s", key, exc_info=True)
            # Cleared last, so a caller that just returned from wait() sees the
            # lease already gone and can immediately submit the key again.
            with _lock:
                _inflight.discard(key)

    threading.Thread(target=_renew, name=f"renew:{key}", daemon=True).start()
    threading.Thread(target=_run, name=f"job:{key}", daemon=True).start()
    return True
