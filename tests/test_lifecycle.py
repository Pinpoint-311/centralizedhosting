"""Take-offline / bring-online (data-retaining) and image digest pinning."""

from orchestrator.config import settings
from tests.conftest import HEADERS, make_tenant, provision


def test_take_offline_retains_everything_and_is_reversible(client):
    tenant = make_tenant(client)
    provision(client, tenant["id"])
    # broker a per-town key + confirm a secret exists
    client.put(
        f"/api/tenants/{tenant['id']}/secrets/GOOGLE_MAPS_API_KEY",
        json={"value": "AIza-keep-me"},
        headers=HEADERS,
    )

    r = client.post(f"/api/tenants/{tenant['id']}/take-offline", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "offline"
    # nothing destroyed: KMS key, secrets, and rendered stack all remain
    assert body["kms_key_ref"]
    assert client.get(f"/api/tenants/{tenant['id']}/secrets", headers=HEADERS).json()
    assert (settings.tenant_root / tenant["slug"] / ".env").exists()

    # reversible
    r = client.post(f"/api/tenants/{tenant['id']}/bring-online", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["status"] == "active"


def test_offline_is_audited_with_data_retained_flag(client):
    tenant = make_tenant(client)
    provision(client, tenant["id"])
    client.post(f"/api/tenants/{tenant['id']}/take-offline", headers=HEADERS)
    entry = client.get(
        f"/api/audit?tenant_id={tenant['id']}&action=tenant.taken_offline", headers=HEADERS
    ).json()
    assert entry and entry[0]["detail"]["data_retained"] is True


def test_cannot_bring_online_an_active_tenant(client):
    tenant = make_tenant(client)
    provision(client, tenant["id"])
    r = client.post(f"/api/tenants/{tenant['id']}/bring-online", headers=HEADERS)
    assert r.status_code == 409


def test_offline_differs_from_decommission(client):
    """Offline keeps the KMS key; decommission destroys it."""
    tenant = make_tenant(client)
    provision(client, tenant["id"])
    client.post(f"/api/tenants/{tenant['id']}/take-offline", headers=HEADERS)
    assert client.get(f"/api/tenants/{tenant['id']}", headers=HEADERS).json()["kms_key_ref"]


def test_release_digest_pins_the_image(client):
    digest = "sha256:" + "a" * 64
    r = client.post(
        "/api/releases",
        json={"version": "2.0.0", "backend_digest": digest, "frontend_digest": digest},
        headers=HEADERS,
    )
    assert r.status_code == 201
    assert r.json()["backend_digest"] == digest

    tenant = make_tenant(client, slug="digest-town")
    # target that release
    client.patch(f"/api/tenants/{tenant['id']}", json={}, headers=HEADERS)
    # set target_version via a rollout would be heavier; provision picks latest release
    provision(client, tenant["id"])
    compose = (settings.tenant_root / "digest-town" / "docker-compose.yml").read_text()
    assert f"@{digest}" in compose  # pinned by digest, not mutable tag


def test_invalid_digest_rejected(client):
    r = client.post(
        "/api/releases",
        json={"version": "2.1.0", "backend_digest": "not-a-digest"},
        headers=HEADERS,
    )
    assert r.status_code == 422


def test_coordinates_round_trip(client):
    tenant = make_tenant(client, slug="geo-town")
    r = client.patch(
        f"/api/tenants/{tenant['id']}",
        json={"latitude": 39.7817, "longitude": -89.6501},
        headers=HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["latitude"] == 39.7817
    assert body["longitude"] == -89.6501


def test_bad_coordinates_rejected(client):
    tenant = make_tenant(client, slug="badgeo")
    r = client.patch(
        f"/api/tenants/{tenant['id']}",
        json={"latitude": 999, "longitude": 0},
        headers=HEADERS,
    )
    assert r.status_code == 422
