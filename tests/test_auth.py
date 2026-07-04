from tests.conftest import HEADERS


def test_healthz_is_open(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_api_requires_token(client):
    assert client.get("/api/tenants").status_code == 401
    assert client.get("/api/tenants", headers={"X-Panel-Token": "wrong"}).status_code == 401


def test_api_accepts_valid_token(client):
    assert client.get("/api/tenants", headers=HEADERS).status_code == 200


def test_fails_closed_when_token_unconfigured(client, monkeypatch):
    from orchestrator.config import settings

    monkeypatch.setattr(settings, "panel_api_token", "")
    assert client.get("/api/tenants", headers=HEADERS).status_code == 503
