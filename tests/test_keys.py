"""Key-responsibility matrix: catalog, per-tenant assignments (three-way),
the shared state credential pool, and their effect on brokering + provisioning."""

from orchestrator.config import settings
from tests.conftest import HEADERS, make_tenant, provision


def test_catalog_lists_assignable_and_infrastructure(client):
    cat = client.get("/api/key-catalog", headers=HEADERS).json()
    ids = {s["id"] for s in cat["assignable"]}
    assert {"maps", "ai", "email_smtp", "identity_sso"} <= ids
    assert "SECRET_KEY" in cat["infrastructure"]
    assert "GOOGLE_MAPS_API_KEY" not in cat["infrastructure"]
    assert set(cat["owners"]) == {"town", "state_shared", "state_per_town"}


def test_defaults_tell_the_intended_story(client):
    tenant = make_tenant(client)
    a = client.get(f"/api/tenants/{tenant['id']}/key-assignments", headers=HEADERS).json()[
        "assignments"
    ]
    # SSO + SMS are town-by-town; metered services are per-town state; shared
    # services are shared.
    assert a["identity_sso"] == "town"
    assert a["sms_twilio"] == "town"
    assert a["maps"] == "state_per_town"
    assert a["ai"] == "state_per_town"
    assert a["email_smtp"] == "state_shared"
    assert a["sentry"] == "state_shared"


def test_legacy_state_value_maps_to_per_town(client):
    resp = client.post(
        "/api/tenants",
        json={"name": "Legacy", "slug": "legacy", "key_assignments": {"identity_sso": "state"}},
        headers=HEADERS,
    )
    assert resp.status_code == 201
    assert resp.json()["key_assignments"]["identity_sso"] == "state_per_town"


def test_switch_identity_to_shared_state_help(client):
    """SSO is town by default, but the state can help via a shared tenant."""
    tenant = make_tenant(client)
    r = client.put(
        f"/api/tenants/{tenant['id']}/key-assignments",
        json={"assignments": {"identity_sso": "state_shared"}},
        headers=HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["assignments"]["identity_sso"] == "state_shared"


def test_per_town_brokering_and_town_refusal(client):
    tenant = make_tenant(client)
    # identity is town-owned by default -> refused
    r = client.put(
        f"/api/tenants/{tenant['id']}/secrets/AUTH0_CLIENT_SECRET",
        json={"value": "x"},
        headers=HEADERS,
    )
    assert r.status_code == 422

    # flip SMS to state_per_town -> its key becomes brokerable per town
    client.put(
        f"/api/tenants/{tenant['id']}/key-assignments",
        json={"assignments": {"sms_twilio": "state_per_town"}},
        headers=HEADERS,
    )
    r = client.put(
        f"/api/tenants/{tenant['id']}/secrets/TWILIO_AUTH_TOKEN",
        json={"value": "tok"},
        headers=HEADERS,
    )
    assert r.status_code == 201


# ---- shared state credential pool ------------------------------------------

def test_shared_pool_rejects_non_catalog_key(client):
    r = client.put("/api/state-credentials/SECRET_KEY", json={"value": "x"}, headers=HEADERS)
    assert r.status_code == 422


def test_shared_pool_write_list_and_never_returns_value(client):
    r = client.put("/api/state-credentials/SMTP_PASSWORD", json={"value": "state-relay-pw"}, headers=HEADERS)
    assert r.status_code == 201
    listing = client.get("/api/state-credentials", headers=HEADERS).json()
    assert listing[0]["key_name"] == "SMTP_PASSWORD"
    assert "state-relay-pw" not in str(listing)


def test_shared_credential_injected_only_for_shared_towns(client):
    # One shared SMTP credential entered once...
    client.put("/api/state-credentials/SMTP_PASSWORD", json={"value": "shared-relay"}, headers=HEADERS)

    # Town A keeps SMTP shared (default) -> gets the pooled value
    a = make_tenant(client, slug="alpha", name="Alpha")
    provision(client, a["id"])
    env_a = (settings.tenant_root / "alpha" / ".env").read_text()
    assert "SMTP_PASSWORD=shared-relay" in env_a

    # Town B sets SMTP to town-owned -> pooled value must NOT leak in
    b = make_tenant(client, slug="bravo", name="Bravo")
    client.put(
        f"/api/tenants/{b['id']}/key-assignments",
        json={"assignments": {"email_smtp": "town"}},
        headers=HEADERS,
    )
    provision(client, b["id"])
    env_b = (settings.tenant_root / "bravo" / ".env").read_text()
    assert "shared-relay" not in env_b


def test_per_town_state_key_lands_in_rendered_stack(client):
    tenant = make_tenant(client, slug="mapleton")
    # maps is state_per_town by default; broker a per-town value
    client.put(
        f"/api/tenants/{tenant['id']}/secrets/GOOGLE_MAPS_API_KEY",
        json={"value": "AIza-mapleton"},
        headers=HEADERS,
    )
    provision(client, tenant["id"])
    env_file = (settings.tenant_root / "mapleton" / ".env").read_text()
    assert "GOOGLE_MAPS_API_KEY=AIza-mapleton" in env_file
    compose = (settings.tenant_root / "mapleton" / "docker-compose.yml").read_text()
    assert "GOOGLE_MAPS_API_KEY" in compose


def test_assignments_and_shared_writes_are_audited(client):
    tenant = make_tenant(client)
    client.put(
        f"/api/tenants/{tenant['id']}/key-assignments",
        json={"assignments": {"maps": "state_shared"}},
        headers=HEADERS,
    )
    client.put("/api/state-credentials/GOOGLE_MAPS_API_KEY", json={"value": "k"}, headers=HEADERS)
    actions = {e["action"] for e in client.get("/api/audit", headers=HEADERS).json()}
    assert "tenant.key_assignments_updated" in actions
    assert "state_credential.written" in actions


def test_update_contact_info(client):
    tenant = make_tenant(client)
    resp = client.patch(
        f"/api/tenants/{tenant['id']}",
        json={"contact_name": "Jane Clerk", "contact_phone": "555-0100", "contact_title": "Town Clerk"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["contact_name"] == "Jane Clerk"
    assert body["contact_phone"] == "555-0100"
