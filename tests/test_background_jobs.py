"""Provisioning runs in the background, not inside the HTTP request.

The pipeline shells out to docker compose with a 10-minute timeout. Inline, a
proxy or browser timeout drops the operator mid-run with no way to tell whether
the town was built. The request now enqueues and answers 202; the job/step rows
are the interface.
"""

import threading
import time

from orchestrator import jobs
from tests.conftest import HEADERS, make_tenant


def test_provision_returns_202_with_a_queued_job(client):
    tenant = make_tenant(client, slug="async-town")
    r = client.post(f"/api/tenants/{tenant['id']}/provision", headers=HEADERS)
    assert r.status_code == 202
    body = r.json()
    assert body["tenant_id"] == tenant["id"]
    assert body["status"] in ("queued", "running", "succeeded")

    assert jobs.wait(f"provision:{tenant['id']}"), "run did not finish"
    finished = client.get(f"/api/tenants/{tenant['id']}/jobs", headers=HEADERS).json()[0]
    assert finished["status"] == "succeeded"
    assert finished["steps"], "the job records its steps for the UI to poll"


def test_a_second_run_is_refused_while_one_is_in_flight(client):
    """Two concurrent pipelines against one town would race on the same
    resources; the operator gets a clear 409 instead."""
    tenant = make_tenant(client, slug="busy-town")
    key = f"provision:{tenant['id']}"
    release = threading.Event()

    assert jobs.submit(key, release.wait)  # occupy the slot
    try:
        r = client.post(f"/api/tenants/{tenant['id']}/provision", headers=HEADERS)
        assert r.status_code == 409 and "already in flight" in r.json()["detail"]
    finally:
        release.set()
        jobs.wait(key)


def test_the_slot_is_released_even_when_the_job_raises(client):
    """A crashed run must not wedge the town so it can never be provisioned
    again — the guard is released in a finally block."""
    key = "provision:boom"

    def explode():
        raise RuntimeError("step blew up")

    assert jobs.submit(key, explode)
    assert jobs.wait(key, timeout=5)
    assert not jobs.is_running(key)
    assert jobs.submit(key, lambda: None)  # slot is reusable
    jobs.wait(key)


def test_decommissioned_tenant_still_refused_before_enqueuing(client):
    tenant = make_tenant(client, slug="gone-town")
    client.post(f"/api/tenants/{tenant['id']}/decommission?confirm_slug=gone-town", headers=HEADERS)
    r = client.post(f"/api/tenants/{tenant['id']}/provision", headers=HEADERS)
    assert r.status_code == 409
    assert not jobs.is_running(f"provision:{tenant['id']}")


def test_wait_reports_timeout_rather_than_hanging(client):
    key = "provision:slow"
    release = threading.Event()
    assert jobs.submit(key, release.wait)
    try:
        started = time.monotonic()
        assert jobs.wait(key, timeout=0.2) is False
        assert time.monotonic() - started < 5
    finally:
        release.set()
        jobs.wait(key)
