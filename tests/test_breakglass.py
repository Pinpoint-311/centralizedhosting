from datetime import datetime, timedelta, timezone

import pytest

from orchestrator.config import settings
from orchestrator.security import mint_break_glass_token, verify_break_glass_token
from tests.conftest import HEADERS, make_tenant


def _issue(client, tenant_id, minutes=30):
    resp = client.post(
        "/api/breakglass",
        json={
            "tenant_id": tenant_id,
            "actor": "ops@state.gov",
            "reason": "Investigating stuck migration for ticket #123",
            "minutes": minutes,
        },
        headers=HEADERS,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_issue_returns_verifiable_token_once(client):
    tenant = make_tenant(client)
    grant = _issue(client, tenant["id"])
    claims = verify_break_glass_token(grant["token"])
    assert claims["tid"] == tenant["id"]
    assert claims["actor"] == "ops@state.gov"
    assert claims["typ"] == "state_ops_break_glass"

    # listing never exposes the token
    listing = client.get("/api/breakglass", headers=HEADERS).json()
    assert "token" not in listing[0]


def test_expiry_is_clamped_to_max(client):
    tenant = make_tenant(client)
    grant = _issue(client, tenant["id"], minutes=100000)
    expires = datetime.fromisoformat(grant["expires_at"])
    limit = datetime.utcnow() + timedelta(minutes=settings.break_glass_max_minutes + 1)
    assert expires < limit


def test_tampered_token_rejected(client):
    tenant = make_tenant(client)
    token = _issue(client, tenant["id"])["token"]
    payload, sig = token.split(".")
    with pytest.raises(ValueError):
        verify_break_glass_token(payload + "." + sig[:-2] + "xx")


def test_expired_token_rejected():
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
    token = mint_break_glass_token("tid", "ops@state.gov", "jti", past)
    with pytest.raises(ValueError, match="expired"):
        verify_break_glass_token(token)


def test_short_reason_rejected(client):
    tenant = make_tenant(client)
    resp = client.post(
        "/api/breakglass",
        json={"tenant_id": tenant["id"], "actor": "ops@state.gov", "reason": "why", "minutes": 5},
        headers=HEADERS,
    )
    assert resp.status_code == 422


def test_revoke_and_audit(client):
    tenant = make_tenant(client)
    grant = _issue(client, tenant["id"])
    revoked = client.post(f"/api/breakglass/{grant['id']}/revoke", headers=HEADERS)
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"] is not None
    # double revoke rejected
    assert client.post(f"/api/breakglass/{grant['id']}/revoke", headers=HEADERS).status_code == 409

    actions = {e["action"] for e in client.get("/api/audit", headers=HEADERS).json()}
    assert {"breakglass.issued", "breakglass.revoked"} <= actions
