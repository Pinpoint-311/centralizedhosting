import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="pp311-panel-test-")
os.environ["PANEL_DATABASE_URL"] = f"sqlite:///{_tmp}/panel.db"
os.environ["PANEL_API_TOKEN"] = "test-token"
os.environ["PANEL_SECRET_KEY"] = "test-secret-key"
os.environ["TENANT_ROOT"] = f"{_tmp}/tenants"
os.environ["APPLY_STACKS"] = "false"
os.environ["BASE_DOMAIN"] = "311.test.gov"
# The suite fires many requests from one client; lift the rate-limit ceiling so
# SlowAPI doesn't 429 mid-run (production keeps the 500/min default).
os.environ["RATE_LIMIT_RPM"] = "1000000"

import pytest
from fastapi.testclient import TestClient

from orchestrator.db import Base, SessionLocal, engine, init_db
from orchestrator.main import app

HEADERS = {"X-Panel-Token": "test-token"}


@pytest.fixture()
def client():
    init_db()
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(engine)


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    yield session
    session.close()


def make_tenant(client, slug="springfield", name="Springfield, IL", **extra):
    resp = client.post(
        "/api/tenants",
        json={"name": name, "slug": slug, "contact_email": f"clerk@{slug}.gov", **extra},
        headers=HEADERS,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def provision(client, tenant_id):
    """Provision and wait for the run to finish.

    Provisioning is enqueued and executed on a background thread (it shells out
    to compose and can take minutes in production), so the API answers 202 with
    a job. Tests exercise that real path and then block on the job rather than
    running a synchronous variant that production never uses.
    """
    from orchestrator import jobs

    resp = client.post(f"/api/tenants/{tenant_id}/provision", headers=HEADERS)
    assert resp.status_code == 202, resp.text
    assert jobs.wait(f"provision:{tenant_id}"), "provisioning did not finish in time"
    jobs_resp = client.get(f"/api/tenants/{tenant_id}/jobs", headers=HEADERS)
    assert jobs_resp.status_code == 200, jobs_resp.text
    return jobs_resp.json()[0]
