"""Feature backends: cost/chargeback, SLA/uptime, alerts, bulk onboarding, tags."""

from datetime import timedelta

from orchestrator.models import TelemetrySnapshot, Tenant, utcnow
from tests.conftest import HEADERS, make_tenant, provision


def _seed_snapshot(db, tenant_id, reachable=True, api_usage=None, version="1.0.0", when=None):
    snap = TelemetrySnapshot(
        tenant_id=tenant_id,
        reachable=reachable,
        version=version,
        payload={"version": version, "api_usage": api_usage or {}},
    )
    if when:
        snap.collected_at = when
    db.add(snap)
    db.commit()
    return snap


# ---- cost / chargeback ------------------------------------------------------

def test_cost_summary_splits_state_vs_town(client, db):
    tenant = make_tenant(client, slug="costtown")
    # maps defaults state_per_town (state-borne); identity would be town.
    _seed_snapshot(
        db, tenant["id"],
        api_usage={
            "maps_geocode": {"calls": 1000},          # state-borne (maps=state_per_town)
            "translation": {"characters": 500000},    # state-borne (translation=state_shared)
        },
    )
    summary = client.get("/api/cost/summary", headers=HEADERS).json()
    assert summary["fleet_total"] > 0
    assert summary["state_borne"] > 0
    town = next(t for t in summary["towns"] if t["slug"] == "costtown")
    assert town["state_borne"] > 0


def test_cost_respects_town_assignment(client, db):
    tenant = make_tenant(client, slug="towncost")
    # flip maps to town-owned -> its cost is town-borne
    client.put(
        f"/api/tenants/{tenant['id']}/key-assignments",
        json={"assignments": {"maps": "town"}},
        headers=HEADERS,
    )
    _seed_snapshot(db, tenant["id"], api_usage={"maps_geocode": {"calls": 1000}})
    summary = client.get("/api/cost/summary", headers=HEADERS).json()
    town = next(t for t in summary["towns"] if t["slug"] == "towncost")
    assert town["town_borne"] > 0
    assert town["state_borne"] == 0


# ---- SLA / uptime -----------------------------------------------------------

def test_sla_computes_uptime_and_incidents(client, db):
    tenant = make_tenant(client, slug="slatown")
    now = utcnow()
    # 3 up, 1 down, 1 up -> 80% uptime, 1 incident
    for i, ok in enumerate([True, True, False, True, True]):
        _seed_snapshot(db, tenant["id"], reachable=ok, when=now - timedelta(hours=5 - i))
    sla = client.get("/api/sla/summary?days=7", headers=HEADERS).json()
    town = next(t for t in sla["towns"] if t["slug"] == "slatown")
    assert town["checks"] == 5
    assert town["uptime_percent"] == 80.0
    assert town["incidents"] == 1


# ---- alerts -----------------------------------------------------------------

def test_alerts_fire_for_down_town_and_ack(client, db):
    tenant = make_tenant(client, slug="downtown")
    provision(client, tenant["id"])
    _seed_snapshot(db, tenant["id"], reachable=False)
    assert client.post("/api/alerts/evaluate", headers=HEADERS).json()["new_alerts"] >= 1

    alerts = client.get("/api/alerts", headers=HEADERS).json()
    down = [a for a in alerts if a["kind"] == "down" and a["tenant_slug"] == "downtown"]
    assert down
    # dedup: evaluating again does not duplicate the open alert
    assert client.post("/api/alerts/evaluate", headers=HEADERS).json()["new_alerts"] == 0
    # ack it
    acked = client.post(f"/api/alerts/{down[0]['id']}/ack", headers=HEADERS).json()
    assert acked["acknowledged_at"] is not None
    assert client.get("/api/alerts?open_only=true", headers=HEADERS).json() == []


def test_drift_alert(client, db):
    tenant = make_tenant(client, slug="drifttown")
    provision(client, tenant["id"])
    # town runs old version; publish a newer release
    t = db.get(Tenant, tenant["id"])
    t.running_version = "1.0.0"
    db.commit()
    client.post("/api/releases", json={"version": "2.0.0"}, headers=HEADERS)
    client.post("/api/alerts/evaluate", headers=HEADERS)
    alerts = client.get("/api/alerts", headers=HEADERS).json()
    assert any(a["kind"] == "drift" and a["tenant_slug"] == "drifttown" for a in alerts)


# ---- bulk onboarding + tags -------------------------------------------------

def test_bulk_create_reports_per_row(client):
    body = {
        "tenants": [
            {"name": "Alpha", "slug": "b-alpha", "tags": ["cohort-1"]},
            {"name": "Beta", "slug": "b-beta"},
            {"name": "Dup", "slug": "b-alpha"},  # duplicate -> fails just this row
        ]
    }
    res = client.post("/api/tenants/bulk", json=body, headers=HEADERS).json()
    # rows are returned in submission order
    assert res[0]["slug"] == "b-alpha" and res[0]["ok"] is True
    assert res[1]["slug"] == "b-beta" and res[1]["ok"] is True
    assert res[2]["ok"] is False and "exists" in res[2]["error"]
    assert sum(1 for r in res if not r["ok"]) == 1


def test_tag_filter(client):
    make_tenant(client, slug="tagged", name="Tagged")
    client.patch(f"/api/tenants/{client.get('/api/tenants', headers=HEADERS).json()[0]['id']}",
                 json={"tags": ["pilot"]}, headers=HEADERS)
    filtered = client.get("/api/tenants?tag=pilot", headers=HEADERS).json()
    assert len(filtered) == 1 and filtered[0]["slug"] == "tagged"
    assert client.get("/api/tenants?tag=nope", headers=HEADERS).json() == []
