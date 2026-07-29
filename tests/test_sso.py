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


def test_federation_editor_is_retired(client):
    """Identity is configured in ONE place — the provider catalog. The old
    federation editor is gone so two screens can't disagree about who signs
    people in."""
    for method, path in (("get", "/api/auth/federation"),
                         ("put", "/api/auth/federation"),
                         ("post", "/api/auth/federation/test")):
        r = getattr(client, method)(path, headers=HEADERS, **({"json": {}} if method == "put" else {}))
        # 404, or 405 where the SPA catch-all claims the path for GET only.
        assert r.status_code in (404, 405), f"{method.upper()} {path} should be gone"


def test_ui_configured_provider_outranks_a_legacy_federation_row(client, db):
    """An upgraded deployment may still carry a FederationConfig row. It must
    keep authenticating, but the Staff Sign-In card has to win — otherwise the
    only remaining editor would silently do nothing."""
    from orchestrator import oidc
    from orchestrator.models import FederationConfig
    from orchestrator.security import encrypt_value

    db.add(FederationConfig(
        id="default", enabled=True, provider="okta",
        issuer="https://legacy.okta.com", client_id="legacy-cid",
        client_secret_encrypted=encrypt_value("legacy-secret"),
    ))
    db.commit()
    # Legacy row alone still signs people in.
    assert oidc.effective_config(db).issuer == "https://legacy.okta.com"

    client.post("/api/providers/identity/save", json={"provider": "auth0", "settings": {
        "AUTH0_DOMAIN": "new.us.auth0.com", "AUTH0_CLIENT_ID": "c", "AUTH0_CLIENT_SECRET": "s",
    }}, headers=HEADERS)
    db.expire_all()
    cfg = oidc.effective_config(db)
    assert cfg.provider == "auth0" and cfg.issuer == "https://new.us.auth0.com"


# ---- Uniform SSO setup: the app's IDENTITY_PROVIDER env catalog ------------

def test_env_provider_catalog_configures_sso(client, monkeypatch):
    """SSO can be set up exactly like the app — via IDENTITY_PROVIDER + the
    provider's env credentials — with no DB config."""
    monkeypatch.setenv("IDENTITY_PROVIDER", "okta")
    monkeypatch.setenv("OKTA_ISSUER", "https://example.okta.com")
    monkeypatch.setenv("OKTA_CLIENT_ID", "cid")
    monkeypatch.setenv("OKTA_CLIENT_SECRET", "sec")
    status = client.get("/api/auth/sso/status").json()
    assert status["configured"] is True
    assert status["provider"] == "okta"


def test_env_provider_issuer_derivation_matches_app(monkeypatch):
    from orchestrator import oidc

    monkeypatch.setenv("IDENTITY_PROVIDER", "auth0")
    monkeypatch.setenv("AUTH0_DOMAIN", "acme.us.auth0.com")
    monkeypatch.setenv("AUTH0_CLIENT_ID", "cid")
    monkeypatch.setenv("AUTH0_CLIENT_SECRET", "sec")
    cfg = oidc.resolve_identity_config()
    assert cfg.provider == "auth0" and cfg.issuer == "https://acme.us.auth0.com"

    monkeypatch.setenv("IDENTITY_PROVIDER", "entra")
    monkeypatch.setenv("ENTRA_TENANT_ID", "tid")
    monkeypatch.setenv("ENTRA_CLIENT_ID", "cid")
    monkeypatch.setenv("ENTRA_CLIENT_SECRET", "sec")
    cfg = oidc.resolve_identity_config()
    assert cfg.issuer == "https://login.microsoftonline.com/tid/v2.0"


def test_env_provider_incomplete_is_unconfigured(monkeypatch):
    from orchestrator import oidc

    monkeypatch.setenv("IDENTITY_PROVIDER", "oidc")
    monkeypatch.setenv("OIDC_ISSUER", "https://idp.example.gov")
    # client id/secret missing -> not configured
    monkeypatch.delenv("OIDC_CLIENT_ID", raising=False)
    monkeypatch.delenv("OIDC_CLIENT_SECRET", raising=False)
    assert oidc.resolve_identity_config() is None
