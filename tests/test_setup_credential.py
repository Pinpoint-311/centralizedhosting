"""The town setup credential (INITIAL_ADMIN_PASSWORD) the state hands off."""

from tests.conftest import HEADERS, make_tenant, provision


def test_setup_password_generated_and_revealable(client):
    t = make_tenant(client, slug="setupville", name="Setupville")
    provision(client, t["id"])

    r = client.get(f"/api/tenants/{t['id']}/setup-credential", headers=HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["initial_admin_password"]  # non-empty
    assert body["setup_url"].endswith(".gov/") or body["setup_url"].startswith("https://")
    assert "rotate" in body["note"].lower()


def test_setup_password_injected_into_town_env(client):
    """It must reach the town's env AND be forwarded into the backend container
    so the app's first-run bootstrap accepts it (not the disabled default)."""
    t = make_tenant(client, slug="envville", name="Envville")
    provision(client, t["id"])
    preview = client.get(f"/api/tenants/{t['id']}/stack-preview", headers=HEADERS).json()
    assert "INITIAL_ADMIN_PASSWORD" in preview["env"]
    # The compose must forward it to the backend container's environment.
    assert "INITIAL_ADMIN_PASSWORD" in preview["compose"]


def test_setup_password_absent_before_provisioning(client):
    t = make_tenant(client, slug="unprov", name="Unprovisioned")
    r = client.get(f"/api/tenants/{t['id']}/setup-credential", headers=HEADERS)
    assert r.status_code == 404


def test_revealing_setup_password_is_audited(client):
    t = make_tenant(client, slug="auditville", name="Auditville")
    provision(client, t["id"])
    before = client.get("/api/audit?limit=200", headers=HEADERS).json()
    client.get(f"/api/tenants/{t['id']}/setup-credential", headers=HEADERS)
    after = client.get("/api/audit?limit=200", headers=HEADERS).json()
    actions = [e["action"] for e in (after if isinstance(after, list) else after.get("entries", []))]
    before_actions = [e["action"] for e in (before if isinstance(before, list) else before.get("entries", []))]
    assert actions.count("tenant.setup_credential_revealed") == before_actions.count("tenant.setup_credential_revealed") + 1
