"""Hosting-provider admin: platform branding/organization, system health/config."""

from tests.conftest import HEADERS


def test_platform_config_defaults_and_branding_in_panel_config(client):
    cfg = client.get("/api/platform/config", headers=HEADERS).json()
    assert cfg["platform_name"] == "Pinpoint 311"
    assert cfg["tagline"] == "Hosting Control Plane"
    assert cfg["org_type"] == "agency"
    # Branding is exposed (unauthenticated) via panel-config for the login screen.
    pc = client.get("/api/panel-config").json()
    assert pc["platform_name"] == "Pinpoint 311"
    assert "tagline" in pc


def test_platform_config_partial_updates_dont_wipe_each_other(client):
    # Save branding only.
    client.put("/api/platform/config", json={"platform_name": "NJ 311 Cloud", "tagline": "State program"}, headers=HEADERS)
    # Then save organization only — must not wipe the branding.
    r = client.put("/api/platform/config", json={"org_legal_name": "NJ Office of Innovation", "org_type": "state"}, headers=HEADERS)
    out = r.json()
    assert out["platform_name"] == "NJ 311 Cloud"          # branding preserved
    assert out["org_legal_name"] == "NJ Office of Innovation"
    assert out["org_type"] == "state"


def test_invalid_org_type_falls_back_to_other(client):
    out = client.put("/api/platform/config", json={"org_type": "galactic-empire"}, headers=HEADERS).json()
    assert out["org_type"] == "other"


def test_system_health_reports_checks_and_fleet(client):
    h = client.get("/api/system/health", headers=HEADERS).json()
    assert set(h["checks"]) >= {"database", "secret_encryption", "audit_chain"}
    assert h["checks"]["database"]["ok"] is True
    assert h["checks"]["audit_chain"]["ok"] is True
    assert "total" in h["fleet"] and "active" in h["fleet"]
    assert h["version"]


def test_system_config_is_readonly_effective_settings(client):
    c = client.get("/api/system/config", headers=HEADERS).json()
    assert "security" in c and "kms_backend" in c["security"]
    assert "backups" in c and "deployment" in c


def test_operators_lists_actors_and_role_context(client):
    from tests.conftest import make_tenant

    make_tenant(client, slug="opsactor")  # generates an audit action
    ops = client.get("/api/operators", headers=HEADERS).json()
    assert ops["you"]["role"] == "admin"
    assert any(o["actor"] for o in ops["operators"])
    assert "default_role" in ops
