from sqlalchemy import select

from orchestrator.models import TelemetrySnapshot
from orchestrator.telemetry import contains_pii_keys, sanitize_telemetry
from tests.conftest import HEADERS, make_tenant, provision


def test_sanitizer_keeps_metadata_and_strips_pii():
    raw = {
        "version": "1.4.0",
        "db_revision": "rev_b",
        "uptime_seconds": 12345,
        "request_counts": {"200": 4000, "500": 3},
        "api_usage": {"vertex_ai": {"calls": 12, "cost": 0.4}},
        # must never survive:
        "recent_reporters": [{"email": "jane@example.com"}],
        "admin_email": "clerk@town.gov",
        "integration_health": {"auth0": "ok", "smtp_password": "hunter2"},
    }
    clean = sanitize_telemetry(raw)
    assert clean["version"] == "1.4.0"
    assert clean["request_counts"] == {"200": 4000, "500": 3}
    assert "recent_reporters" not in clean  # not allowlisted
    assert "admin_email" not in clean
    assert clean["integration_health"] == {"auth0": "ok"}  # nested PII-ish key stripped
    assert not contains_pii_keys(clean)


def test_contains_pii_keys_detects_nested():
    assert contains_pii_keys({"a": [{"b": {"reporter_phone": "555"}}]})
    assert not contains_pii_keys({"request_counts": {"200": 1}})


def test_fleet_refresh_stores_pii_free_snapshots(client, db):
    tenant = make_tenant(client)
    provision(client, tenant["id"])

    resp = client.post("/api/fleet/refresh", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["polled"] == 1
    # No town is actually running in tests -> unreachable, but a snapshot exists
    snap = db.execute(select(TelemetrySnapshot)).scalars().one()
    assert snap.reachable is False
    # Regression guard: whatever lands in a snapshot must be PII-key-free
    assert not contains_pii_keys({k: v for k, v in snap.payload.items() if k != "error"})


def test_fleet_summary_reports_drift(client):
    tenant = make_tenant(client)
    provision(client, tenant["id"])
    client.post("/api/releases", json={"version": "9.9.9"}, headers=HEADERS)

    summary = client.get("/api/fleet/summary", headers=HEADERS).json()
    assert summary["tenants_total"] == 1
    assert summary["latest_release"] == "9.9.9"
    assert summary["drifted"] == 1
    town = summary["towns"][0]
    assert town["drift"] is True
    assert town["host"] == "springfield.311.test.gov"

    drift = client.get("/api/fleet/drift", headers=HEADERS).json()
    assert drift["drifted_towns"][0]["slug"] == "springfield"
