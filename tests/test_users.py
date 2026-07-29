"""Operator (User) management + password login, ported from the app's model.

Single role: every active user is admin-equivalent. The X-Panel-Token holder
bootstraps the first operators; they then log in (password here, SSO in prod)
and their JWT bearer authenticates every route.
"""

from tests.conftest import HEADERS, TEST_PASSWORD, TEST_USERNAME


def _create(client, username=TEST_USERNAME, email=None):
    return client.post(
        "/api/users",
        json={"username": username, "email": email or f"{username}@example.gov", "full_name": "Op"},
        headers=HEADERS,
    )


def test_token_holder_bootstraps_first_user(client):
    r = _create(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["role"] == "admin" and body["is_active"] is True
    assert body["has_password"] is False and body["auth"] == "invited"


def test_duplicate_username_and_email_rejected(client):
    # 400 + wording match the app's create_user.
    _create(client, "dup", "dup@example.gov")
    r = _create(client, "dup", "other@example.gov")
    assert r.status_code == 400 and r.json()["detail"] == "Username already exists"
    r = _create(client, "other", "dup@example.gov")
    assert r.status_code == 400 and r.json()["detail"] == "Email already exists"


def test_cannot_delete_yourself(client):
    """Self-delete is refused by id, as the app does — and a machine caller
    (X-Panel-Token, no User row) has no account of its own to protect."""
    uid = _create(client, "selfie").json()["id"]
    client.post(f"/api/users/{uid}/reset-password", json={"password": TEST_PASSWORD}, headers=HEADERS)
    token = client.post("/api/auth/login",
                        json={"username": "selfie", "password": TEST_PASSWORD}).json()["access_token"]
    bearer = {"Authorization": f"Bearer {token}"}
    r = client.delete(f"/api/users/{uid}", headers=bearer)
    assert r.status_code == 400 and r.json()["detail"] == "Cannot delete yourself"
    # The same account can still be removed by another admin / the token holder.
    assert client.delete(f"/api/users/{uid}", headers=HEADERS).status_code == 204


def test_password_login_mints_jwt_that_authenticates(client):
    uid = _create(client, "loginuser").json()["id"]
    client.post(f"/api/users/{uid}/reset-password", json={"password": TEST_PASSWORD}, headers=HEADERS)
    r = client.post("/api/auth/login", json={"username": "loginuser", "password": TEST_PASSWORD})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    bearer = {"Authorization": f"Bearer {token}"}
    # The JWT authenticates /auth/me and any protected route — no panel token.
    me = client.get("/api/auth/me", headers=bearer).json()
    assert me["username"] == "loginuser" and me["via"] == "user"
    assert client.get("/api/tenants", headers=bearer).status_code == 200


def test_wrong_password_and_no_password_rejected(client):
    uid = _create(client, "nopw").json()["id"]
    # No password set yet → cannot log in.
    assert client.post("/api/auth/login", json={"username": "nopw", "password": "x"}).status_code == 401
    client.post(f"/api/users/{uid}/reset-password", json={"password": "right-password-1234"}, headers=HEADERS)
    assert client.post("/api/auth/login", json={"username": "nopw", "password": "wrong"}).status_code == 401


def test_deactivated_user_cannot_log_in(client):
    uid = _create(client, "gone").json()["id"]
    client.post(f"/api/users/{uid}/reset-password", json={"password": "temp-password-1234"}, headers=HEADERS)
    client.put(f"/api/users/{uid}", json={"is_active": False}, headers=HEADERS)
    assert client.post("/api/auth/login", json={"username": "gone", "password": "temp-password-1234"}).status_code == 403


def test_delete_user(client):
    uid = _create(client, "temp").json()["id"]
    assert client.delete(f"/api/users/{uid}", headers=HEADERS).status_code == 204
    assert not any(u["username"] == "temp" for u in client.get("/api/users", headers=HEADERS).json())


def test_me_via_panel_token_is_synthetic(client):
    me = client.get("/api/auth/me", headers=HEADERS).json()
    assert me["via"] == "token" and me["role"] == "admin"
