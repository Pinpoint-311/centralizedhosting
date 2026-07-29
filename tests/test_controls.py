"""Security controls and the key-payer default, driven from the portal.

These used to be environment variables, so the Security posture panel could only
report. The portal is now authoritative — a saved value beats the environment —
which is exactly why the guardrails below matter more than the toggles do.
"""

import pytest

from orchestrator import platform_settings
from orchestrator.config import settings
from orchestrator.models import PlatformConfig, Tenant
from tests.conftest import HEADERS, make_tenant


@pytest.fixture(autouse=True)
def restore_settings():
    """These tests deliberately mutate the process-wide settings object — that
    is the mechanism under test — so put it back, or the next test file inherits
    a posture it never asked for."""
    saved = {c["key"]: getattr(settings, c["key"]) for c in platform_settings.CONTROLS}
    yield
    for key, value in saved.items():
        setattr(settings, key, value)


def _controls(client):
    return {c["key"]: c for c in
            client.get("/api/system/controls", headers=HEADERS).json()["controls"]}


def _set(client, key, value, confirm=False):
    return client.put(f"/api/system/controls/{key}",
                      json={"value": value, "confirm": confirm}, headers=HEADERS)


def test_controls_report_value_and_where_it_came_from(client):
    controls = _controls(client)
    assert {"require_kms", "cosign_verify", "backups_enabled", "ssl_check_enabled",
            "apply_stacks", "waf_enabled", "require_signed_images",
            "rate_limit_rpm"} <= set(controls)
    assert controls["ssl_check_enabled"]["source"] == "environment"


def test_a_portal_toggle_takes_effect_immediately(client):
    """No restart: the saved value lands on the settings object the rest of the
    codebase already reads."""
    assert settings.ssl_check_enabled is False
    assert _set(client, "ssl_check_enabled", True).status_code == 200
    assert settings.ssl_check_enabled is True

    controls = _controls(client)
    assert controls["ssl_check_enabled"]["value"] is True
    assert controls["ssl_check_enabled"]["source"] == "portal"


def test_portal_value_beats_the_environment(client, monkeypatch):
    """The deployment says one thing, the portal says another, and the portal
    wins — that is the model chosen for this panel."""
    monkeypatch.setattr(settings, "ssl_check_enabled", True)
    assert _set(client, "ssl_check_enabled", False, confirm=True).status_code == 200

    # A fresh process re-reading stored values arrives at the portal's answer.
    monkeypatch.setattr(settings, "ssl_check_enabled", True)
    from orchestrator.db import SessionLocal

    with SessionLocal() as db:
        platform_settings.apply(db)
    assert settings.ssl_check_enabled is False


def test_a_control_that_cannot_work_is_refused_not_saved(client):
    """Turning on signature verification with no cosign binary would fail every
    rollout. Refuse, and say what is missing."""
    r = _set(client, "cosign_verify", True)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "cosign" in detail.lower()
    assert settings.cosign_verify is False  # nothing was persisted


def test_requiring_kms_without_a_kms_is_refused(client):
    r = _set(client, "require_kms", True)
    assert r.status_code == 422 and "KMS" in r.json()["detail"]


def test_backups_cannot_be_enabled_without_a_bucket(client):
    r = _set(client, "backups_enabled", True)
    assert r.status_code == 422 and "BACKUP_S3" in r.json()["detail"]


def test_weakening_a_control_needs_an_explicit_confirmation(client, monkeypatch):
    """The portal is authoritative, so nothing blocks an operator who means it —
    but a fleet-wide protection must not come off by a stray click."""
    monkeypatch.setattr(settings, "require_signed_images", True)

    unconfirmed = _set(client, "require_signed_images", False)
    assert unconfirmed.status_code == 422
    assert "confirm" in unconfirmed.json()["detail"].lower()
    assert settings.require_signed_images is True

    assert _set(client, "require_signed_images", False, confirm=True).status_code == 200
    assert settings.require_signed_images is False


def test_turning_on_real_deploys_also_needs_confirmation(client, monkeypatch):
    """apply_stacks is the one control whose dangerous direction is ON: the next
    provision stops rendering files and starts deploying containers."""
    monkeypatch.setattr(settings, "apply_stacks", False)
    assert _set(client, "apply_stacks", True).status_code == 422
    assert _set(client, "apply_stacks", True, confirm=True).status_code == 200


def test_every_control_change_is_audited_with_who_and_what(client):
    _set(client, "ssl_check_enabled", True)
    entries = client.get("/api/audit", headers=HEADERS).json()
    entry = next(e for e in entries if e["action"] == "system.control_changed")
    assert entry["detail"]["control"] == "ssl_check_enabled"
    assert entry["detail"]["value"] is True
    assert entry["detail"]["previous"] is False


def test_rate_limit_is_a_number_with_bounds(client):
    assert _set(client, "rate_limit_rpm", 250).status_code == 200
    assert settings.rate_limit_rpm == 250
    assert _set(client, "rate_limit_rpm", -5).status_code == 422
    assert _set(client, "rate_limit_rpm", "many").status_code == 422


def test_unknown_control_is_rejected(client):
    assert _set(client, "database_url", "postgres://evil").status_code == 422


def test_waf_toggle_rerenders_the_fleet(client, db):
    """The WAF lives in each town's Caddy config, so flipping it has to rewrite
    the files — otherwise the switch would report on while nothing changed."""
    t = make_tenant(client, slug="waftown")
    from tests.conftest import provision

    provision(client, t["id"])

    r = _set(client, "waf_enabled", True)
    assert r.status_code == 200
    assert r.json()["effect"] == "rerender"
    assert r.json()["rerender"]["rendered"] >= 1

    from orchestrator import stack

    site = stack.caddy_sites_dir() / "waftown.caddy"
    assert "coraza" in site.read_text().lower()


# ---- who provides (and pays for) each key ---------------------------------


def test_key_defaults_start_from_the_catalog(client):
    body = client.get("/api/platform/key-defaults", headers=HEADERS).json()
    assert body["owners"] == ["town", "state_shared", "state_per_town"]
    # Metered spend defaults to per-town so billing stays attributable.
    assert body["defaults"]["maps"] == "state_per_town"
    assert body["drift"] == {}


def test_a_new_town_inherits_the_fleet_default(client, db):
    client.put("/api/platform/key-defaults",
               json={"assignments": {"maps": "town"}}, headers=HEADERS)

    t = make_tenant(client, slug="inheritor")
    assert db.get(Tenant, t["id"]).key_assignments["maps"] == "town"


def test_changing_the_default_does_not_re_bill_existing_towns(client, db):
    """Re-pointing who pays for Maps across a live fleet is a billing event, so
    saving a default must not silently move existing towns."""
    t = make_tenant(client, slug="established")
    before = dict(db.get(Tenant, t["id"]).key_assignments)

    client.put("/api/platform/key-defaults",
               json={"assignments": {"maps": "town"}}, headers=HEADERS)

    assert db.get(Tenant, t["id"]).key_assignments == before

    body = client.get("/api/platform/key-defaults", headers=HEADERS).json()
    assert body["drift"]["maps"] == 1  # and the drift is visible


def test_apply_to_all_is_a_separate_deliberate_action(client, db):
    t = make_tenant(client, slug="movable")
    client.put("/api/platform/key-defaults",
               json={"assignments": {"maps": "town"}}, headers=HEADERS)

    r = client.post("/api/platform/key-defaults/apply-to-all", headers=HEADERS)
    assert r.status_code == 200
    assert "movable" in r.json()["changed"]
    assert db.get(Tenant, t["id"]).key_assignments["maps"] == "town"

    body = client.get("/api/platform/key-defaults", headers=HEADERS).json()
    assert body["drift"] == {}

    actions = {e["action"] for e in client.get("/api/audit", headers=HEADERS).json()}
    assert {"platform.key_defaults_set", "platform.key_defaults_applied"} <= actions


def test_an_unknown_owner_is_dropped_rather_than_stored(client):
    client.put("/api/platform/key-defaults",
               json={"assignments": {"maps": "whoever", "nonsense": "town"}},
               headers=HEADERS)
    defaults = client.get("/api/platform/key-defaults", headers=HEADERS).json()["defaults"]
    assert defaults["maps"] == "state_per_town"  # catalog default, not "whoever"
    assert "nonsense" not in defaults
