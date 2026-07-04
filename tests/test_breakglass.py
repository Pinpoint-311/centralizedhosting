from datetime import datetime, timedelta, timezone

import pytest

from orchestrator.config import settings
from orchestrator.provisioner import get_platform_secret
from orchestrator.security import mint_break_glass_token, verify_break_glass_token
from tests.conftest import HEADERS, make_tenant, provision


def _provisioned_tenant(client):
    tenant = make_tenant(client)
    provision(client, tenant["id"])
    return tenant


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
    return resp


def test_issue_requires_provisioned_tenant(client):
    tenant = make_tenant(client)  # not provisioned -> no PROVISIONING_TOKEN yet
    resp = _issue(client, tenant["id"])
    assert resp.status_code == 409


def test_issue_returns_token_verifiable_with_town_key(client, db):
    tenant = _provisioned_tenant(client)
    resp = _issue(client, tenant["id"])
    assert resp.status_code == 201, resp.text
    grant = resp.json()

    # The token verifies against the town's own PROVISIONING_TOKEN — the same
    # check the app performs in its A8 break-glass exchange.
    town_key = get_platform_secret(db, tenant["id"], "PROVISIONING_TOKEN")
    claims = verify_break_glass_token(grant["token"], town_key)
    assert claims["tid"] == tenant["id"]
    assert claims["actor"] == "ops@state.gov"
    assert claims["typ"] == "state_ops_break_glass"

    # ...and NOT against any other key (per-town isolation)
    with pytest.raises(ValueError):
        verify_break_glass_token(grant["token"], "some-other-town-key")

    # listing never exposes the token
    listing = client.get("/api/breakglass", headers=HEADERS).json()
    assert "token" not in listing[0]


def test_expiry_is_clamped_to_max(client):
    tenant = _provisioned_tenant(client)
    grant = _issue(client, tenant["id"], minutes=100000).json()
    expires = datetime.fromisoformat(grant["expires_at"])
    limit = datetime.utcnow() + timedelta(minutes=settings.break_glass_max_minutes + 1)
    assert expires < limit


def test_tampered_token_rejected(client, db):
    tenant = _provisioned_tenant(client)
    token = _issue(client, tenant["id"]).json()["token"]
    town_key = get_platform_secret(db, tenant["id"], "PROVISIONING_TOKEN")
    payload, sig = token.split(".")
    with pytest.raises(ValueError):
        verify_break_glass_token(payload + "." + sig[:-2] + "xx", town_key)


def test_expired_token_rejected():
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
    token = mint_break_glass_token("tid", "ops@state.gov", "jti", past, "town-key")
    with pytest.raises(ValueError, match="expired"):
        verify_break_glass_token(token, "town-key")


def test_short_reason_rejected(client):
    tenant = _provisioned_tenant(client)
    resp = client.post(
        "/api/breakglass",
        json={"tenant_id": tenant["id"], "actor": "ops@state.gov", "reason": "why", "minutes": 5},
        headers=HEADERS,
    )
    assert resp.status_code == 422


def test_revoke_and_audit(client):
    tenant = _provisioned_tenant(client)
    grant = _issue(client, tenant["id"]).json()
    revoked = client.post(f"/api/breakglass/{grant['id']}/revoke", headers=HEADERS)
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"] is not None
    # double revoke rejected
    assert client.post(f"/api/breakglass/{grant['id']}/revoke", headers=HEADERS).status_code == 409

    actions = {e["action"] for e in client.get("/api/audit", headers=HEADERS).json()}
    assert {"breakglass.issued", "breakglass.revoked"} <= actions
