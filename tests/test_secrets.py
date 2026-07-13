from sqlalchemy import select

from orchestrator.models import PlatformSecret
from tests.conftest import HEADERS, make_tenant


def test_platform_managed_key_accepted(client):
    tenant = make_tenant(client)
    resp = client.put(
        f"/api/tenants/{tenant['id']}/secrets/KMS_KEY_RING",
        json={"value": "projects/state/keyRings/pp311"},
        headers=HEADERS,
    )
    assert resp.status_code == 201
    assert resp.json()["key_name"] == "KMS_KEY_RING"


def test_backup_prefix_accepted(client):
    tenant = make_tenant(client)
    resp = client.put(
        f"/api/tenants/{tenant['id']}/secrets/BACKUP_S3_KEY",
        json={"value": "abc"},
        headers=HEADERS,
    )
    assert resp.status_code == 201


def test_town_owned_keys_never_touch_the_panel(client):
    tenant = make_tenant(client)
    # identity + SMS default to the town; a non-catalog key is never brokerable.
    for key in ("AUTH0_CLIENT_SECRET", "TWILIO_AUTH_TOKEN", "OPENAI_API_KEY"):
        resp = client.put(
            f"/api/tenants/{tenant['id']}/secrets/{key}",
            json={"value": "nope"},
            headers=HEADERS,
        )
        assert resp.status_code == 422, key
        assert "town's responsibility" in resp.json()["detail"]


def test_shared_key_is_redirected_to_the_pool(client):
    tenant = make_tenant(client)
    # SMTP defaults to state_shared — its value belongs in the shared pool,
    # not a per-town write.
    resp = client.put(
        f"/api/tenants/{tenant['id']}/secrets/SMTP_PASSWORD",
        json={"value": "nope"},
        headers=HEADERS,
    )
    assert resp.status_code == 422
    assert "shared state credential" in resp.json()["detail"]


def test_per_town_state_key_is_brokered(client):
    tenant = make_tenant(client)
    # Maps defaults to state_per_town — a per-town value is accepted.
    resp = client.put(
        f"/api/tenants/{tenant['id']}/secrets/GOOGLE_MAPS_API_KEY",
        json={"value": "AIza-per-town"},
        headers=HEADERS,
    )
    assert resp.status_code == 201


def test_secret_values_are_never_returned_and_encrypted_at_rest(client, db):
    tenant = make_tenant(client)
    client.put(
        f"/api/tenants/{tenant['id']}/secrets/SECRET_KEY",
        json={"value": "super-secret-value"},
        headers=HEADERS,
    )
    listing = client.get(f"/api/tenants/{tenant['id']}/secrets", headers=HEADERS).json()
    assert listing == [
        {"key_name": "SECRET_KEY", "updated_at": listing[0]["updated_at"]}
    ]
    assert "super-secret-value" not in str(listing)

    row = db.execute(
        select(PlatformSecret).where(PlatformSecret.tenant_id == tenant["id"])
    ).scalar_one()
    assert "super-secret-value" not in row.encrypted_value


def test_secret_writes_audited_without_values(client):
    tenant = make_tenant(client)
    client.put(
        f"/api/tenants/{tenant['id']}/secrets/SECRET_KEY",
        json={"value": "super-secret-value"},
        headers=HEADERS,
    )
    entries = client.get(
        f"/api/audit?tenant_id={tenant['id']}&action=secret.written", headers=HEADERS
    ).json()
    assert entries
    assert "super-secret-value" not in str(entries)


def test_delete_secret(client):
    tenant = make_tenant(client)
    client.put(
        f"/api/tenants/{tenant['id']}/secrets/SECRET_KEY",
        json={"value": "v"},
        headers=HEADERS,
    )
    assert (
        client.delete(f"/api/tenants/{tenant['id']}/secrets/SECRET_KEY", headers=HEADERS).status_code
        == 204
    )
    assert client.get(f"/api/tenants/{tenant['id']}/secrets", headers=HEADERS).json() == []
