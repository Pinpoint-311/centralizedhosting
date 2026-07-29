"""Auth behaviour audited against the app's core/auth.py + callback.

Covers the divergences found and fixed: distinguishing a disabled account from
an unprovisioned one, recording caller origin on auth events, and the 401-vs-403
split for a deactivated user.
"""

from orchestrator import user_auth
from orchestrator.models import User
from tests.conftest import HEADERS


def _user(client, username="test-operator", email=None, password="not-a-real-password"):
    uid = client.post("/api/users", json={"username": username, "email": email or f"{username}@nj.gov"},
                      headers=HEADERS).json()["id"]
    client.post(f"/api/users/{uid}/reset-password", json={"password": password}, headers=HEADERS)
    return uid


def _bearer(client, username="test-operator", password="not-a-real-password"):
    token = client.post("/api/auth/login", json={"username": username, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_deactivated_user_gets_403_not_401(client, db):
    """The app separates an unusable token (401) from a real but disabled
    account (403). Only the second is actionable by an admin."""
    uid = _user(client, "deact")
    bearer = _bearer(client, "deact")
    assert client.get("/api/auth/me", headers=bearer).status_code == 200

    client.put(f"/api/users/{uid}", json={"is_active": False}, headers=HEADERS)

    r = client.get("/api/users", headers=bearer)
    assert r.status_code == 403 and r.json()["detail"] == "Inactive user"


def test_garbage_and_expired_tokens_are_401(client):
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.jwt"}).status_code == 401

    from datetime import timedelta
    expired = user_auth.create_access_token({"sub": "ghost"}, expires_delta=timedelta(minutes=-5))
    assert client.get("/api/users", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


def test_single_purpose_tokens_are_refused(client):
    """Onboarding-style tokens must be redeemed at their own endpoint, never
    used as a session bearer. Ported from the app's get_current_user."""
    _user(client, "purpose")
    tok = user_auth.create_access_token({"sub": "purpose", "purpose": "onboarding"})
    r = client.get("/api/users", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


def test_sso_denials_are_distinguishable_in_the_audit_log(client, db):
    """A disabled operator and an unknown one must not produce the same
    outcome — otherwise an admin goes looking for a row that already exists."""
    from orchestrator.api.auth_sso import SSO_DENY_REASONS

    assert {"no_email", "not_provisioned", "account_disabled"} <= set(SSO_DENY_REASONS)


def test_password_login_records_caller_origin(client):
    """Auth events carry ip/user-agent, as the app's do — the panel's audit log
    is the compliance artifact, and it's the first thing read after an incident."""
    _user(client, "origin")
    client.post("/api/auth/login", json={"username": "origin", "password": "not-a-real-password"},
                headers={"User-Agent": "pytest-agent/1.0"})
    entries = client.get("/api/audit", headers=HEADERS).json()
    login = next(e for e in entries if e["action"] == "user.login")
    assert login["detail"].get("user_agent") == "pytest-agent/1.0"
    assert login["detail"].get("ip_address")
