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


def test_system_config_reports_deployment_and_security_posture(client):
    c = client.get("/api/system/config", headers=HEADERS).json()
    assert "deployment" in c and c["deployment"]["base_domain"]

    # Posture is a list of controls, each carrying what its state means — not a
    # flat on/off dump, which couldn't distinguish a finding from a fact.
    keys = {p["key"] for p in c["posture"]}
    assert keys == {"require_kms", "require_signed_images", "cosign_verify",
                    "waf_enabled", "rate_limit", "backups_enabled", "ssl_check_enabled"}
    for control in c["posture"]:
        assert control["detail"]  # every control explains itself either way
        assert control["severity"] == "ok" if control["enabled"] else control["severity"] in ("warning", "info")

    assert c["summary"]["total"] == len(c["posture"])
    assert c["summary"]["enabled"] == sum(1 for p in c["posture"] if p["enabled"])
    assert c["summary"]["warnings"] == sum(1 for p in c["posture"] if p["severity"] == "warning")


def test_system_config_does_not_duplicate_system_health(client):
    """KMS backend and loop intervals belong to System Health. Repeating them
    here invites the two views to drift apart."""
    c = client.get("/api/system/config", headers=HEADERS).json()
    flat = str(c)
    assert "kms_backend" not in flat
    assert "alert_poll_seconds" not in flat and "telemetry_poll_seconds" not in flat


def test_operators_lists_actors_and_role_context(client):
    from tests.conftest import make_tenant

    make_tenant(client, slug="opsactor")  # generates an audit action
    ops = client.get("/api/operators", headers=HEADERS).json()
    assert ops["you"]["role"] == "admin"
    assert any(o["actor"] for o in ops["operators"])
    # The retired federation row no longer decides this — it reports the SSO
    # actually in force, and there is no role map to report with one role.
    assert ops["sso_enabled"] is False and ops["sso_provider"] is None
    assert "role_map" not in ops and "default_role" not in ops
