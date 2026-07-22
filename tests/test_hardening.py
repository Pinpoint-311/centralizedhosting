"""Government-production hardening round 2: KMS envelope encryption, cosign
verification, WORM/SIEM audit shipping, PITR backups, WAF + rate limiting,
SSL/health alerting, and the oauth2-proxy SSO/MFA sidecar."""

import json

from orchestrator.config import settings
from tests.conftest import HEADERS, make_tenant, provision


# ---- 1. Cloud KMS / HSM envelope encryption --------------------------------

def test_kms_envelope_encryption_roundtrips_and_wraps_dek(client, db, monkeypatch):
    """With KEY_PROVIDER=kms the DEK is generated, wrapped by the KMS, and only
    the wrapped form is persisted — yet secrets still encrypt/decrypt."""
    from orchestrator import key_provider
    from orchestrator.models import WrappedKey
    from orchestrator.security import decrypt_value, encrypt_value

    monkeypatch.setattr(settings, "key_provider", "kms")
    monkeypatch.setattr(settings, "kms_backend", "local-hsm")
    monkeypatch.setattr(settings, "kms_kek_material", "unit-test-kek-material")
    monkeypatch.setattr(settings, "panel_kek_version", 1)
    key_provider.reset_cache()

    ct = encrypt_value("super-secret-value")
    assert ct.startswith("v1:")
    assert decrypt_value(ct) == "super-secret-value"

    row = db.get(WrappedKey, 1)
    assert row is not None
    assert row.backend == "local-hsm"
    # The DB holds only the *wrapped* DEK — never the plaintext key material.
    assert "super-secret-value" not in row.wrapped_dek
    assert len(row.wrapped_dek) > 0

    key_provider.reset_cache()


def test_kms_rotation_still_decrypts_old_versions(client, db, monkeypatch):
    from orchestrator import key_provider
    from orchestrator.security import decrypt_value, encrypt_value

    monkeypatch.setattr(settings, "key_provider", "kms")
    monkeypatch.setattr(settings, "kms_backend", "local-hsm")
    monkeypatch.setattr(settings, "kms_kek_material", "rotate-kek")
    key_provider.reset_cache()

    monkeypatch.setattr(settings, "panel_kek_version", 1)
    old = encrypt_value("legacy")
    monkeypatch.setattr(settings, "panel_kek_version", 2)
    new = encrypt_value("current")

    assert old.startswith("v1:") and new.startswith("v2:")
    assert decrypt_value(old) == "legacy"   # unwrapped via the v1 wrapped DEK
    assert decrypt_value(new) == "current"  # via the freshly-wrapped v2 DEK
    key_provider.reset_cache()


# ---- 2. cosign signature verification --------------------------------------

def _pin_release(client, version):
    digest = "sha256:" + "c" * 64
    client.post(
        "/api/releases",
        json={"version": version, "backend_digest": digest, "frontend_digest": digest},
        headers=HEADERS,
    )


def test_cosign_verify_passes_when_signatures_valid(client, monkeypatch):
    from orchestrator import supply_chain

    monkeypatch.setattr(settings, "require_signed_images", True)
    monkeypatch.setattr(settings, "cosign_verify", True)
    monkeypatch.setattr(supply_chain, "_run_cosign", lambda ref: (True, "signature verified"))
    _pin_release(client, "8.0.0")

    t = make_tenant(client, slug="signed-ok")
    job = provision(client, t["id"])
    assert job["status"] == "succeeded"
    step = {s["name"]: s for s in job["steps"]}["verify_supply_chain"]
    assert "cosign-verified" in step["detail"]


def test_cosign_verify_fails_closed_on_bad_signature(client, monkeypatch):
    from orchestrator import supply_chain

    monkeypatch.setattr(settings, "require_signed_images", True)
    monkeypatch.setattr(settings, "cosign_verify", True)
    monkeypatch.setattr(supply_chain, "_run_cosign", lambda ref: (False, "no matching signatures"))
    _pin_release(client, "8.0.1")

    t = make_tenant(client, slug="signed-bad")
    job = provision(client, t["id"])
    assert job["status"] == "failed"
    step = {s["name"]: s for s in job["steps"]}["verify_supply_chain"]
    assert step["status"] == "failed"
    assert "cosign" in step["detail"].lower()


# ---- 3. WORM + SIEM audit shipping -----------------------------------------

def test_audit_ships_to_worm_journal(client, db, tmp_path, monkeypatch):
    from orchestrator.models import AuditLog
    from sqlalchemy import select

    worm = tmp_path / "audit.ndjson"
    monkeypatch.setattr(settings, "audit_worm_path", str(worm))

    make_tenant(client, slug="wormtown")

    assert worm.exists()
    lines = [json.loads(x) for x in worm.read_text().splitlines() if x.strip()]
    assert lines, "expected at least one shipped audit line"
    last = db.execute(select(AuditLog).order_by(AuditLog.seq.desc()).limit(1)).scalar_one()
    # The shipped record carries the on-host hash chain, verifiable off-host.
    assert lines[-1]["entry_hash"] == last.entry_hash
    assert lines[-1]["seq"] == last.seq


def test_audit_ships_to_siem(client, monkeypatch):
    from orchestrator import audit_ship

    captured = []
    monkeypatch.setattr(settings, "audit_siem_url", "https://siem.example.gov/collect")
    monkeypatch.setattr(audit_ship, "_post_siem", lambda rec: captured.append(rec))

    make_tenant(client, slug="siemtown")
    assert captured, "expected a SIEM ship"
    assert "action" in captured[-1] and "entry_hash" in captured[-1]


# ---- 4. PITR backups -------------------------------------------------------

def test_backup_records_planned_without_apply(client):
    t = make_tenant(client, slug="backuptown")
    provision(client, t["id"])
    r = client.post(f"/api/tenants/{t['id']}/backup", headers=HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "base"
    assert body["status"] == "planned"  # APPLY_STACKS=false in tests

    lst = client.get(f"/api/tenants/{t['id']}/backups", headers=HEADERS).json()
    assert lst["pitr_enabled"] is False
    assert len(lst["backups"]) == 1


def test_pitr_wal_archiving_in_town_stack_when_enabled(client, monkeypatch):
    monkeypatch.setattr(settings, "backups_enabled", True)
    t = make_tenant(client, slug="pitrtown")
    provision(client, t["id"])
    compose = (settings.tenant_root / "pitrtown" / "docker-compose.yml").read_text()
    assert "archive_mode=on" in compose
    assert "pgbackups:/backups" in compose


# ---- 5. WAF + rate limiting ------------------------------------------------

def test_waf_and_rate_limit_rendered_in_caddy_site(client, monkeypatch):
    monkeypatch.setattr(settings, "waf_enabled", True)
    t = make_tenant(client, slug="waftown")
    provision(client, t["id"])
    site = (settings.tenant_root / "_caddy" / "waftown.caddy").read_text()
    assert "coraza_waf" in site
    assert "rate_limit" in site
    assert "Strict-Transport-Security" in site


def test_security_headers_present_without_waf(client):
    """Baseline security headers ship even when the WAF module isn't enabled."""
    t = make_tenant(client, slug="hdrtown")
    provision(client, t["id"])
    site = (settings.tenant_root / "_caddy" / "hdrtown.caddy").read_text()
    assert "Strict-Transport-Security" in site
    assert "coraza_waf" not in site  # WAF stays off by default


# ---- 6. SSL / health alerting ----------------------------------------------

def test_cert_expiry_alert_raised(client, db, monkeypatch):
    from orchestrator import insights, sslcheck

    monkeypatch.setattr(settings, "ssl_check_enabled", True)
    monkeypatch.setattr(settings, "cert_expiry_warn_days", 30)
    monkeypatch.setattr(sslcheck, "days_until_expiry", lambda host, **kw: 5)

    t = make_tenant(client, slug="certtown")
    provision(client, t["id"])
    new = insights.evaluate_alerts(db)
    kinds = {a.kind for a in new}
    assert "cert_expiry" in kinds
    crit = [a for a in new if a.kind == "cert_expiry"][0]
    assert crit.severity == "critical"  # 5 days <= warn//3 (10)


def test_no_cert_alert_when_cert_healthy(client, db, monkeypatch):
    from orchestrator import insights, sslcheck

    monkeypatch.setattr(settings, "ssl_check_enabled", True)
    monkeypatch.setattr(settings, "cert_expiry_warn_days", 30)
    monkeypatch.setattr(sslcheck, "days_until_expiry", lambda host, **kw: 200)

    t = make_tenant(client, slug="freshcert")
    provision(client, t["id"])
    new = insights.evaluate_alerts(db)
    assert "cert_expiry" not in {a.kind for a in new}


def test_health_alert_from_unhealthy_integration(client, db):
    from orchestrator import insights
    from orchestrator.models import TelemetrySnapshot

    t = make_tenant(client, slug="degraded")
    provision(client, t["id"])
    db.add(TelemetrySnapshot(
        tenant_id=t["id"], reachable=True, version="1.0.0",
        payload={"integration_health": {"kms": {"ok": False, "status": "error"}}},
    ))
    db.commit()
    new = insights.evaluate_alerts(db)
    assert "health" in {a.kind for a in new}


# ---- 7. oauth2-proxy SSO/MFA sidecar ---------------------------------------

def test_sidecar_config_rendered_from_federation(client):
    client.put(
        "/api/auth/federation",
        json={
            "enabled": False,
            "provider": "oidc",
            "issuer": "https://login.example.gov",
            "client_id": "panel-client",
            "client_secret": "topsecret",
            "groups_claim": "groups",
            "group_role_map": {"pp311-admins": "admin", "pp311-ops": "operator"},
            "default_role": "viewer",
        },
        headers=HEADERS,
    )
    cfg = client.get("/api/auth/sidecar-config", headers=HEADERS)
    assert cfg.status_code == 200, cfg.text
    body = cfg.json()
    assert 'oidc_issuer_url = "https://login.example.gov"' in body["config"]
    assert 'client_id = "panel-client"' in body["config"]
    # The client secret is NEVER inlined — only referenced as an env var.
    assert "topsecret" not in body["config"]
    assert "${OAUTH2_PROXY_CLIENT_SECRET}" in body["config"]
    # Only recognized groups may sign in.
    assert set(body["allowed_groups"]) == {"pp311-admins", "pp311-ops"}
    assert "oauth2-proxy" in body["compose"]
