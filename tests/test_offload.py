"""Municipality offload: self-host bundle generation + migration lifecycle."""

from tests.conftest import HEADERS, make_tenant, provision


def _offload(client, tid):
    return client.post(f"/api/tenants/{tid}/offload", headers=HEADERS)


def test_offload_generates_bundle_and_marks_migrating(client):
    t = make_tenant(client, slug="leaving", name="Leaving Town")
    provision(client, t["id"])
    r = _offload(client, t["id"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "migrating"
    assert "docker-compose.yml" in body["bundle"]
    assert ".env" in body["bundle"]
    assert "MIGRATION_RUNBOOK.md" in body["bundle"]

    # The bundle is downloadable as a gzip archive.
    dl = client.get(f"/api/tenants/{t['id']}/offload/bundle", headers=HEADERS)
    assert dl.status_code == 200
    assert dl.headers["content-type"] == "application/gzip"
    assert len(dl.content) > 0


def test_bundle_is_standalone_and_carries_the_towns_keys(client):
    t = make_tenant(client, slug="standalone", name="Standalone")
    provision(client, t["id"])
    _offload(client, t["id"])
    p = client.get(f"/api/tenants/{t['id']}/offload/preview", headers=HEADERS).json()

    # Un-managed: no state control plane in the standalone stack.
    assert 'MANAGED_MODE: "false"' in p["compose"]
    assert "PROVISIONING_TOKEN" not in p["compose"]
    # The town takes its own SECRET_KEY so existing encrypted data still decrypts.
    assert "SECRET_KEY" in p["env"]
    assert "MANAGED_MODE=false" in p["env"]
    # Runbook explains the data migration + rotation.
    assert "pg" in p["runbook"].lower()
    assert "rotate" in p["runbook"].lower()


def test_offload_complete_marks_migrated(client):
    t = make_tenant(client, slug="donemigrating", name="Done")
    provision(client, t["id"])
    _offload(client, t["id"])
    r = client.post(f"/api/tenants/{t['id']}/offload/complete", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["status"] == "migrated"


def test_offload_cancel_restores_active(client):
    t = make_tenant(client, slug="changedmind", name="Changed Mind")
    provision(client, t["id"])
    _offload(client, t["id"])
    r = client.post(f"/api/tenants/{t['id']}/offload/cancel", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["status"] == "active"


def test_complete_requires_migrating_state(client):
    t = make_tenant(client, slug="notmigrating", name="Not Migrating")
    provision(client, t["id"])
    # Never started an offload -> complete should 409.
    assert client.post(f"/api/tenants/{t['id']}/offload/complete", headers=HEADERS).status_code == 409
