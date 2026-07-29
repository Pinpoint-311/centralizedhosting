"""Panel sign-in enforcement — the app's bootstrap gate, ported.

Password sign-in is the first-run path only. The moment an identity provider is
configured (Auth0 / Entra / Okta / generic OIDC, from env, the legacy
FederationConfig, or the provider store the UI writes), it is refused and people
must use SSO.
"""

from orchestrator import oidc
from tests.conftest import HEADERS


def _make_user_with_password(client, username="test-operator", password="not-a-real-password"):
    uid = client.post("/api/users", json={"username": username, "email": f"{username}@nj.gov"},
                      headers=HEADERS).json()["id"]
    client.post(f"/api/users/{uid}/reset-password", json={"password": password}, headers=HEADERS)
    return uid


def _configure_entra(client):
    return client.post("/api/providers/identity/save", json={"provider": "entra", "settings": {
        "ENTRA_TENANT_ID": "aaaa-bbbb", "ENTRA_CLIENT_ID": "cid", "ENTRA_CLIENT_SECRET": "sec",
    }}, headers=HEADERS)


def test_status_before_and_after_configuring_an_idp(client):
    s = client.get("/api/auth/status").json()
    assert s["auth0_configured"] is False and s["bootstrap_available"] is True
    assert s["provider"] is None

    _configure_entra(client)

    s = client.get("/api/auth/status").json()
    assert s["auth0_configured"] is True and s["bootstrap_available"] is False
    assert s["provider"] == "entra" and s["message"] == "Ready"


def test_password_login_works_only_until_an_idp_is_configured(client):
    _make_user_with_password(client)
    assert client.post("/api/auth/login",
                       json={"username": "test-operator", "password": "not-a-real-password"}).status_code == 200

    _configure_entra(client)

    r = client.post("/api/auth/login", json={"username": "test-operator", "password": "not-a-real-password"})
    assert r.status_code == 403 and "single sign-on is configured" in r.json()["detail"].lower()


def test_gate_is_presence_based_not_reachability_based(client):
    """An unreachable IdP must NOT re-open password sign-in — that is the whole
    point of the app's fail-closed gate."""
    _make_user_with_password(client, "gated")
    # A syntactically valid but entirely unreachable issuer.
    client.post("/api/providers/identity/save", json={"provider": "oidc", "settings": {
        "OIDC_ISSUER": "https://unreachable.invalid/oauth2",
        "OIDC_CLIENT_ID": "cid", "OIDC_CLIENT_SECRET": "sec",
    }}, headers=HEADERS)

    r = client.post("/api/auth/login", json={"username": "gated", "password": "not-a-real-password"})
    assert r.status_code == 403


def test_provider_store_drives_sso_with_the_apps_issuer_derivation(client, db):
    _configure_entra(client)
    cfg = oidc.effective_config(db)
    assert cfg is not None and cfg.provider == "entra"
    # The app's derivation: https://{authority}/{tenant}/v2.0
    assert cfg.issuer == "https://login.microsoftonline.com/aaaa-bbbb/v2.0"
    assert cfg.client_id == "cid" and cfg.client_secret == "sec"

    client.post("/api/providers/identity/save", json={"provider": "auth0", "settings": {
        "AUTH0_DOMAIN": "acme.us.auth0.com", "AUTH0_CLIENT_ID": "c", "AUTH0_CLIENT_SECRET": "s",
    }}, headers=HEADERS)
    assert oidc.effective_config(db).issuer == "https://acme.us.auth0.com"

    client.post("/api/providers/identity/save", json={"provider": "okta", "settings": {
        "OKTA_ISSUER": "https://acme.okta.com/oauth2/default/",
        "OKTA_CLIENT_ID": "c", "OKTA_CLIENT_SECRET": "s",
    }}, headers=HEADERS)
    assert oidc.effective_config(db).issuer == "https://acme.okta.com/oauth2/default"  # trailing / trimmed


def test_partially_configured_provider_does_not_close_the_gate(client):
    """Selecting a provider without its secret must not lock out first-run
    access — the app requires ALL credentials before treating it as configured."""
    _make_user_with_password(client, "partial")
    client.post("/api/providers/identity/save", json={"provider": "okta", "settings": {
        "OKTA_ISSUER": "https://acme.okta.com/oauth2/default",
    }}, headers=HEADERS)

    assert client.get("/api/auth/status").json()["bootstrap_available"] is True
    assert client.post("/api/auth/login",
                       json={"username": "partial", "password": "not-a-real-password"}).status_code == 200


def test_machine_token_still_works_after_sso_is_enforced(client):
    """Gating human password sign-in must not strand automation — X-Panel-Token
    is a service credential, and it is also the operator's way back in if the
    IdP is misconfigured."""
    _configure_entra(client)
    assert client.get("/api/tenants", headers=HEADERS).status_code == 200
    assert client.get("/api/auth/me", headers=HEADERS).json()["via"] == "token"
