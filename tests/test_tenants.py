from pathlib import Path

from orchestrator.config import settings
from tests.conftest import HEADERS, make_tenant, provision


def test_create_and_list(client):
    tenant = make_tenant(client)
    assert tenant["status"] == "pending"
    assert tenant["subdomain"] == "springfield"
    assert client.get("/api/tenants", headers=HEADERS).json()[0]["slug"] == "springfield"


def test_duplicate_slug_rejected(client):
    make_tenant(client)
    resp = client.post(
        "/api/tenants",
        json={"name": "Other", "slug": "springfield"},
        headers=HEADERS,
    )
    assert resp.status_code == 409


def test_invalid_slug_rejected(client):
    resp = client.post(
        "/api/tenants", json={"name": "Bad", "slug": "Not A Slug!"}, headers=HEADERS
    )
    assert resp.status_code == 422


def test_provision_dry_run_renders_hardened_stack(client):
    tenant = make_tenant(client)
    job = provision(client, tenant["id"])
    assert job["status"] == "succeeded"

    by_name = {s["name"]: s for s in job["steps"]}
    assert by_name["allocate_database"]["status"] == "done"
    assert by_name["render_stack"]["status"] == "done"
    # Render-only mode defers apply + town bootstrap
    assert by_name["apply_stack"]["status"] == "skipped"
    assert by_name["app_bootstrap"]["status"] == "skipped"

    refreshed = client.get(f"/api/tenants/{tenant['id']}", headers=HEADERS).json()
    assert refreshed["status"] == "active"
    assert refreshed["kms_key_ref"]
    assert refreshed["backend_port"]

    compose = (settings.tenant_root / "springfield" / "docker-compose.yml").read_text()
    # A2 hosted hardening: managed mode on, no docker socket, no watchtower
    assert 'MANAGED_MODE: "true"' in compose
    assert "docker.sock" not in compose
    assert "containrrr/watchtower" not in compose
    env_file = settings.tenant_root / "springfield" / ".env"
    assert env_file.exists()
    assert (env_file.stat().st_mode & 0o777) == 0o600
    assert (settings.tenant_root / "_caddy" / "springfield.caddy").exists()


def test_provision_is_idempotent(client):
    tenant = make_tenant(client)
    provision(client, tenant["id"])
    second = provision(client, tenant["id"])
    assert second["status"] == "succeeded"
    by_name = {s["name"]: s for s in second["steps"]}
    for step in ("allocate_database", "generate_secret_key", "assign_kms_key",
                 "allocate_storage", "allocate_ports"):
        assert by_name[step]["status"] == "skipped", step


def test_port_allocation_is_unique(client):
    a = make_tenant(client, slug="alpha")
    b = make_tenant(client, slug="beta")
    provision(client, a["id"])
    provision(client, b["id"])
    pa = client.get(f"/api/tenants/{a['id']}", headers=HEADERS).json()["backend_port"]
    pb = client.get(f"/api/tenants/{b['id']}", headers=HEADERS).json()["backend_port"]
    assert pa != pb


def test_suspend_resume(client):
    tenant = make_tenant(client)
    provision(client, tenant["id"])
    assert (
        client.post(f"/api/tenants/{tenant['id']}/suspend", headers=HEADERS).json()["status"]
        == "suspended"
    )
    assert (
        client.post(f"/api/tenants/{tenant['id']}/resume", headers=HEADERS).json()["status"]
        == "active"
    )


def test_decommission_crypto_shreds(client):
    tenant = make_tenant(client)
    provision(client, tenant["id"])

    # wrong confirmation aborts
    resp = client.post(
        f"/api/tenants/{tenant['id']}/decommission?confirm_slug=nope", headers=HEADERS
    )
    assert resp.status_code == 400

    resp = client.post(
        f"/api/tenants/{tenant['id']}/decommission?confirm_slug=springfield", headers=HEADERS
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "decommissioned"
    assert body["kms_key_ref"] is None  # wrapping key destroyed -> PII unrecoverable

    # brokered secrets removed, rendered stack gone
    assert client.get(f"/api/tenants/{tenant['id']}/secrets", headers=HEADERS).json() == []
    assert not (settings.tenant_root / "springfield").exists()

    # audited with crypto_shred flag
    audit = client.get(
        f"/api/audit?tenant_id={tenant['id']}&action=tenant.decommissioned", headers=HEADERS
    ).json()
    assert audit and audit[0]["detail"]["crypto_shred"] is True


def test_provisioning_actions_are_audited(client):
    tenant = make_tenant(client)
    provision(client, tenant["id"])
    actions = {e["action"] for e in client.get("/api/audit", headers=HEADERS).json()}
    assert {"tenant.created", "tenant.provision.started", "tenant.provision.succeeded"} <= actions
