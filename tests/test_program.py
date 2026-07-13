"""County-level analytics wall, legal hold (shared), managed settings, compliance,
transparency, announcements, and the richer intake."""

from orchestrator.config import settings
from orchestrator.models import TelemetrySnapshot, Tenant, utcnow
from tests.conftest import HEADERS, make_tenant, provision


def _snap(db, tenant_id, reachable=True, request_stats=None, legal_hold=False):
    db.add(TelemetrySnapshot(
        tenant_id=tenant_id, collected_at=utcnow(), reachable=reachable,
        version="1.0.0",
        payload={"version": "1.0.0", "request_stats": request_stats or {}, "legal_hold": legal_hold},
    ))
    db.commit()


def _town(client, slug, county):
    t = make_tenant(client, slug=slug, name=slug.title())
    client.patch(f"/api/tenants/{t['id']}", json={"county": county}, headers=HEADERS)
    return t


# ---- the analytics wall -----------------------------------------------------

def test_analytics_is_region_only_never_town_by_town(client, db, monkeypatch):
    monkeypatch.setattr(settings, "analytics_min_cell", 2)
    # 2 towns in "Alpha County", 1 in "Beta County"
    a1 = _town(client, "a1", "Alpha County")
    a2 = _town(client, "a2", "Alpha County")
    b1 = _town(client, "b1", "Beta County")
    _snap(db, a1["id"], request_stats={"total": 100, "closed": 90, "by_category": {"Pothole": 60}})
    _snap(db, a2["id"], request_stats={"total": 50, "closed": 40, "by_category": {"pothole": 20}})
    _snap(db, b1["id"], request_stats={"total": 30, "closed": 10, "by_category": {"Noise": 30}})

    data = client.get("/api/analytics", headers=HEADERS).json()
    # No per-town data anywhere in the response
    assert "towns" not in data
    body = str(data)
    for slug in ("a1", "a2", "b1"):
        assert slug not in body
    # Alpha County (2 towns) shows; Beta County (1 town) is below min_cell -> withheld
    region_key = settings.region_label.lower()
    regions = {r[region_key] for r in data["regions"]}
    assert "Alpha County" in regions
    assert "Beta County" not in regions
    assert data["towns_withheld_for_privacy"] == 1
    assert data["program_total_requests"] == 180  # all still counted program-wide


def test_category_mapping_rolls_up_to_canonical(client, db):
    t = _town(client, "cat", "Alpha County")
    _town(client, "cat2", "Alpha County")  # ensure region shows (min_cell default 3? set 1)
    client.put(
        f"/api/tenants/{t['id']}/category-mappings",
        json={"mappings": {"pothole": "road_pothole", "street hole": "road_pothole"}},
        headers=HEADERS,
    )
    _snap(db, t["id"], request_stats={"total": 10, "by_category": {"Pothole": 6, "Street Hole": 4}})
    data = client.get("/api/analytics", headers=HEADERS).json()
    assert data["by_canonical_category"].get("road_pothole") == 10


# ---- legal hold (shared) ----------------------------------------------------

def test_legal_hold_is_shared_state_or_town(client, db):
    t = make_tenant(client, slug="hold")
    # state places hold
    r = client.post(f"/api/tenants/{t['id']}/legal-hold",
                    json={"on": True, "reason": "Litigation X v. Town"}, headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["state_hold"] is True and r.json()["effective"] is True

    # state lifts; but town has its own hold reported via telemetry -> still effective
    _snap(db, t["id"], legal_hold=True)
    r = client.post(f"/api/tenants/{t['id']}/legal-hold",
                    json={"on": False, "reason": "State matter closed"}, headers=HEADERS)
    body = r.json()
    assert body["state_hold"] is False
    assert body["town_hold"] is True
    assert body["effective"] is True  # town's hold still holds


def test_legal_hold_audited_with_reason(client):
    t = make_tenant(client, slug="hold2")
    client.post(f"/api/tenants/{t['id']}/legal-hold",
                json={"on": True, "reason": "records request pending"}, headers=HEADERS)
    entries = client.get(f"/api/audit?tenant_id={t['id']}&action=tenant.legal_hold_set", headers=HEADERS).json()
    assert entries and entries[0]["detail"]["reason"] == "records request pending"


# ---- managed settings -------------------------------------------------------

def test_managed_settings_catalog_marks_scope(client):
    cat = client.get("/api/managed-settings/catalog", headers=HEADERS).json()["catalog"]
    by_key = {c["key"]: c for c in cat}
    assert by_key["legal_hold"]["scope"] == "shared"
    assert by_key["retention_days"]["scope"] == "state"


def test_managed_settings_round_trip(client):
    t = make_tenant(client, slug="ms")
    r = client.put(f"/api/tenants/{t['id']}/managed-settings",
                   json={"settings": {"retention_days": 1825, "require_mfa": True}}, headers=HEADERS)
    assert r.status_code == 200
    got = client.get(f"/api/tenants/{t['id']}/managed-settings", headers=HEADERS).json()["settings"]
    assert got["retention_days"] == 1825
    assert got["require_mfa"] is True


# ---- compliance -------------------------------------------------------------

def test_compliance_summary_scores_posture(client):
    t = make_tenant(client, slug="comp")
    provision(client, t["id"])  # assigns KMS key -> encryption check passes
    data = client.get("/api/compliance/summary", headers=HEADERS).json()
    town = next(x for x in data["towns"] if x["slug"] == "comp")
    assert town["checks"]["encryption"] is True
    assert 0 <= town["score"] <= 100


# ---- transparency -----------------------------------------------------------

def test_transparency_states_no_resident_data_and_lists_access(client):
    t = make_tenant(client, slug="trans")
    provision(client, t["id"])
    client.post(f"/api/tenants/{t['id']}/legal-hold", json={"on": True, "reason": "audit demo"}, headers=HEADERS)
    rep = client.get(f"/api/tenants/{t['id']}/transparency", headers=HEADERS).json()
    assert any("PII" in x or "personally identifiable" in x for x in rep["panel_never_holds"])
    assert any(e["action"] == "tenant.legal_hold_set" for e in rep["state_access_events"])


# ---- announcements + public status -----------------------------------------

def test_announcement_and_public_status(client):
    client.post("/api/announcements",
                json={"title": "Planned maintenance Sat 2am", "severity": "maintenance"}, headers=HEADERS)
    # public status needs no auth
    status = client.get("/api/status").json()
    assert status["overall"] == "maintenance"
    assert any(a["title"].startswith("Planned maintenance") for a in status["announcements"])


# ---- richer intake ----------------------------------------------------------

def test_intake_ref_code_and_carryover(client, monkeypatch):
    monkeypatch.setattr(settings, "public_requests_enabled", True)
    req = client.post("/api/requests", json={
        "name": "Riverside", "requested_slug": "riverside", "county": "Alpha County",
        "contact_email": "clerk@riverside.gov", "contact_phone": "555-1000",
        "details": {"population": 42000, "current_system": "SeeClickFix"},
        "key_preferences": {"maps": "town", "identity_sso": "town"},
    }).json()
    assert req["ref_code"].startswith("REQ-")
    assert req["details"]["population"] == 42000

    tenant = client.post(f"/api/requests/{req['id']}/approve", headers=HEADERS).json()
    assert tenant["county"] == "Alpha County"
    assert tenant["contact_phone"] == "555-1000"
    assert tenant["key_assignments"]["maps"] == "town"  # carried over


def test_intake_honeypot_rejects_bot(client, monkeypatch):
    monkeypatch.setattr(settings, "public_requests_enabled", True)
    r = client.post("/api/requests", json={"name": "Spamville", "website": "http://spam"})
    # accepted silently but NOT stored
    assert r.status_code == 201
    listed = client.get("/api/requests", headers=HEADERS).json()
    assert all(x["name"] != "Spamville" for x in listed)
