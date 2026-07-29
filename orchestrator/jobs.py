"""Background execution for long-running orchestration.

Provisioning shells out to ``docker compose`` with a 10-minute timeout. Run
inline it holds an HTTP request open for the whole run, so a proxy or browser
timeout drops the client mid-provision — the work continues server-side, but the
operator is left staring at a failed request with no idea whether their town was
built. The job/step rows already existed to describe a run; this makes them the
actual interface: the request enqueues and returns immediately, and the UI polls.

Single-process by design, matching how the panel is deployed (one uvicorn
worker). ``_inflight`` is therefore an in-process guard; moving to multiple
workers needs a database-level lock instead — see docs/OPERATIONS.md.
"""

import logging
import threading

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_inflight: set[str] = set()


def is_running(key: str) -> bool:
    with _lock:
        return key in _inflight


def running_keys() -> set[str]:
    with _lock:
        return set(_inflight)


def _claim(key: str) -> bool:
    """Reserve a key, or report that it is already being worked on."""
    with _lock:
        if key in _inflight:
            return False
        _inflight.add(key)
        return True


def _release(key: str) -> None:
    with _lock:
        _inflight.discard(key)


def wait(key: str, timeout: float = 120.0, interval: float = 0.01) -> bool:
    """Block until ``key`` finishes. Returns False if it was still running when
    the timeout elapsed. Used by callers that genuinely need the result inline —
    tests, and any CLI that wants to report the outcome rather than a job id."""
    import time

    deadline = time.monotonic() + timeout
    while is_running(key) and time.monotonic() < deadline:
        time.sleep(interval)
    return not is_running(key)


def submit(key: str, fn, *args, **kwargs) -> bool:
    """Run ``fn`` on a background thread under a one-at-a-time ``key``.

    Returns False when that key is already in flight — the caller should tell
    the operator rather than starting a second concurrent run. ``fn`` is
    responsible for opening (and closing) its own database session: the request
    that submitted the work has already returned, so its session is gone.
    """
    if not _claim(key):
        return False

    def _run():
        try:
            fn(*args, **kwargs)
        except Exception:  # noqa: BLE001 — a crashed job must not kill the thread pool
            logger.exception("background job %s failed", key)
        finally:
            _release(key)

    threading.Thread(target=_run, name=f"job:{key}", daemon=True).start()
    return True
