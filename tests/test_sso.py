"""Operator SSO: session-cookie auth, role gating, and federation config."""

from orchestrator.config import settings
from orchestrator.security import mint_session
from tests.conftest import HEADERS

COOKIE = settings.session_cookie_name


def test_sso_status_reports_unconfigured(client):
    r = client.get("/api/auth/sso/status")
    assert r.status_code == 200
    assert r.json()["configured"] is False


def test_session_cookie_authenticates_without_token(client):
    # A valid session cookie authenticates on its own (no X-Panel-Token).
    token = mint_session("ops@state.gov", "operator")
    r = client.get("/api/tenants", cookies={COOKIE: token})
    assert r.status_code == 200


def test_session_role_is_enforced(client):
    # A viewer session can read but not create a tenant (needs operator).
    viewer = mint_session("viewer@state.gov", "viewer")
    assert client.get("/api/tenants", cookies={COOKIE: viewer}).status_code == 200
    r = client.post("/api/tenants", json={"name": "X", "slug": "x"}, cookies={COOKIE: viewer})
    assert r.status_code == 403


def test_tampered_session_is_rejected(client):
    r = client.get("/api/tenants", cookies={COOKIE: "not.a.jwt"})
    # No valid cookie and no token -> unauthorized.
    assert r.status_code in (401, 403, 503)


def test_federation_save_masks_secret_and_enables(client):
    body = {
        "enabled": True,
        "provider": "okta",
        "issuer": "https://example.okta.com",
        "client_id": "abc123",
        "client_secret": "super-secret-value",
        "groups_claim": "groups",
        "group_role_map": {"pp-admins": "admin", "pp-ops": "operator"},
        "default_role": "viewer",
    }
    r = client.put("/api/auth/federation", json=body, headers=HEADERS)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["enabled"] is True
    assert out["client_secret_set"] is True
    assert "super-secret-value" not in r.text  # secret never returned
    assert "client_secret" not in out

    # Status now reports configured.
    assert client.get("/api/auth/sso/status").json()["configured"] is True


def test_federation_enable_requires_credentials(client):
    r = client.put("/api/auth/federation", json={"enabled": True, "issuer": "", "client_id": ""}, headers=HEADERS)
    assert r.status_code == 422


def test_federation_secret_persists_when_omitted(client):
    base = {"enabled": True, "provider": "oidc", "issuer": "https://idp.example.gov",
            "client_id": "cid", "client_secret": "s3cret", "default_role": "viewer"}
    client.put("/api/auth/federation", json=base, headers=HEADERS)
    # Update without resupplying the secret -> stays set.
    upd = dict(base); upd.pop("client_secret")
    r = client.put("/api/auth/federation", json=upd, headers=HEADERS)
    assert r.json()["client_secret_set"] is True


def test_invalid_role_in_map_rejected(client):
    body = {"enabled": False, "issuer": "https://idp", "client_id": "c",
            "group_role_map": {"g": "superuser"}, "default_role": "viewer"}
    assert client.put("/api/auth/federation", json=body, headers=HEADERS).status_code == 422
