"""Key-responsibility matrix: catalog, per-tenant assignments, and the effect
on what the panel will broker."""

from orchestrator.config import settings
from tests.conftest import HEADERS, make_tenant, provision


def test_catalog_lists_assignable_and_infrastructure(client):
    cat = client.get("/api/key-catalog", headers=HEADERS).json()
    ids = {s["id"] for s in cat["assignable"]}
    assert {"maps", "ai", "email_smtp", "identity_sso"} <= ids
    # infrastructure keys are always state-owned (locked in the UI)
    assert "SECRET_KEY" in cat["infrastructure"]
    assert "GOOGLE_MAPS_API_KEY" not in cat["infrastructure"]
    assert set(cat["owners"]) == {"state", "town"}


def test_defaults_applied_on_create(client):
    tenant = make_tenant(client)
    assignments = client.get(
        f"/api/tenants/{tenant['id']}/key-assignments", headers=HEADERS
    ).json()["assignments"]
    assert assignments["maps"] == "town"       # town by default
    assert assignments["sentry"] == "state"    # state by default


def test_assigning_service_to_state_allows_brokering(client):
    tenant = make_tenant(client)
    # town-owned by default -> panel refuses the key
    r = client.put(
        f"/api/tenants/{tenant['id']}/secrets/GOOGLE_MAPS_API_KEY",
        json={"value": "AIza-test"},
        headers=HEADERS,
    )
    assert r.status_code == 422

    # flip Maps to the state
    client.put(
        f"/api/tenants/{tenant['id']}/key-assignments",
        json={"assignments": {"maps": "state"}},
        headers=HEADERS,
    )
    # now the panel brokers it
    r = client.put(
        f"/api/tenants/{tenant['id']}/secrets/GOOGLE_MAPS_API_KEY",
        json={"value": "AIza-test"},
        headers=HEADERS,
    )
    assert r.status_code == 201


def test_state_provided_key_lands_in_rendered_stack(client):
    tenant = make_tenant(client, slug="mapleton")
    client.put(
        f"/api/tenants/{tenant['id']}/key-assignments",
        json={"assignments": {"maps": "state"}},
        headers=HEADERS,
    )
    client.put(
        f"/api/tenants/{tenant['id']}/secrets/GOOGLE_MAPS_API_KEY",
        json={"value": "AIza-brokered"},
        headers=HEADERS,
    )
    provision(client, tenant["id"])

    env_file = (settings.tenant_root / "mapleton" / ".env").read_text()
    assert "GOOGLE_MAPS_API_KEY=AIza-brokered" in env_file
    compose = (settings.tenant_root / "mapleton" / "docker-compose.yml").read_text()
    assert "GOOGLE_MAPS_API_KEY" in compose


def test_create_with_initial_assignments(client):
    resp = client.post(
        "/api/tenants",
        json={
            "name": "Riverton",
            "slug": "riverton",
            "key_assignments": {"maps": "state", "email_smtp": "state"},
        },
        headers=HEADERS,
    )
    assert resp.status_code == 201
    assignments = resp.json()["key_assignments"]
    assert assignments["maps"] == "state"
    assert assignments["email_smtp"] == "state"
    assert assignments["identity_sso"] == "town"  # untouched default


def test_assignments_are_audited(client):
    tenant = make_tenant(client)
    client.put(
        f"/api/tenants/{tenant['id']}/key-assignments",
        json={"assignments": {"maps": "state"}},
        headers=HEADERS,
    )
    actions = {e["action"] for e in client.get("/api/audit", headers=HEADERS).json()}
    assert "tenant.key_assignments_updated" in actions


def test_update_contact_info(client):
    tenant = make_tenant(client)
    resp = client.patch(
        f"/api/tenants/{tenant['id']}",
        json={
            "contact_name": "Jane Clerk",
            "contact_phone": "555-0100",
            "contact_title": "Town Clerk",
            "address": "1 Main St",
        },
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["contact_name"] == "Jane Clerk"
    assert body["contact_phone"] == "555-0100"
    assert body["contact_title"] == "Town Clerk"
