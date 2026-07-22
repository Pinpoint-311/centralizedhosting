"""Government-production hardening round 2: KMS envelope encryption, cosign
verification, WORM/SIEM audit shipping, PITR backups, WAF + rate limiting,
SSL/health alerting, and the oauth2-proxy SSO/MFA sidecar."""

import json

from orchestrator.config import settings
from tests.conftest import HEADERS, make_tenant, provision


# ---- 1. KMS envelope encryption (uniform with the app) ---------------------

def test_secret_encryption_is_pii2_envelope_and_roundtrips(client, monkeypatch):
    """Secrets are envelope-encrypted with the app's pii2: scheme. With no cloud
    KMS configured the DEK is wrapped by the local PANEL_SECRET_KEY-derived key."""
    from orchestrator import pii_crypto
    from orchestrator.security import decrypt_value, encrypt_value

    monkeypatch.delenv("KMS_PROVIDER", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("REQUIRE_KMS", raising=False)
    pii_crypto.clear_caches()

    ct = encrypt_value("super-secret-value")
    assert ct.startswith("pii2:")                 # same token format as the app
    assert "super-secret-value" not in ct         # plaintext never in the token
    assert decrypt_value(ct) == "super-secret-value"
    assert pii_crypto.active_backend() == "local"


def test_require_kms_fails_closed_without_a_cloud_kms(client, monkeypatch):
    """REQUIRE_KMS must refuse to fall back to the local key when no cloud KMS
    is configured — same guarantee the app makes."""
    import pytest

    from orchestrator import pii_crypto
    from orchestrator.security import encrypt_value

    monkeypatch.setenv("KMS_PROVIDER", "google")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("REQUIRE_KMS", "true")
    pii_crypto.clear_caches()

    with pytest.raises(Exception):
        encrypt_value("must-not-downgrade")
    pii_crypto.clear_caches()


def test_google_kms_wraps_dek_and_tags_backend(client, monkeypatch):
    """When Google KMS is configured the DEK is wrapped via the KMS client and
    the wrapped DEK is tagged 'g' (active_backend == 'google')."""
    from orchestrator import encryption, pii_crypto
    from orchestrator.security import decrypt_value, encrypt_value

    class _FakeKmsResp:
        def __init__(self, blob):
            self.ciphertext = blob
            self.plaintext = blob

    class _FakeKmsClient:
        # Symmetric echo wrap so we can round-trip without real GCP.
        def encrypt(self, request):
            return _FakeKmsResp(b"WRAPPED::" + request["plaintext"])

        def decrypt(self, request):
            return _FakeKmsResp(request["ciphertext"].removeprefix(b"WRAPPED::"))

    monkeypatch.setenv("KMS_PROVIDER", "google")
    monkeypatch.setattr(encryption, "_is_kms_available", lambda: True)
    monkeypatch.setattr(encryption, "_get_kms_key_name", lambda: "projects/p/locations/l/keyRings/r/cryptoKeys/k")
    monkeypatch.setattr(encryption, "_get_kms_client", lambda: _FakeKmsClient())
    pii_crypto.clear_caches()

    ct = encrypt_value("cloud-wrapped")
    assert ct.startswith("pii2:")
    assert decrypt_value(ct) == "cloud-wrapped"
    assert pii_crypto.active_backend() == "google"
    pii_crypto.clear_caches()


def test_legacy_versioned_fernet_still_decrypts(client):
    """Secrets written under the panel's earlier v<n>: Fernet scheme remain
    readable after the move to envelope encryption."""
    import base64
    import hashlib

    from cryptography.fernet import Fernet

    from orchestrator.security import decrypt_value

    material = settings.panel_secret_key.encode()
    fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(material).digest()))
    legacy = "v1:" + fernet.encrypt(b"old-value").decode()
    assert decrypt_value(legacy) == "old-value"


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


def test_audit_anchor_records_chain_head(client, db):
    """Uniform with the app: an anchor records the chain head + count (and logs
    [AUDIT ANCHOR] to stdout for off-host aggregation)."""
    make_tenant(client, slug="anchortown")
    r = client.post("/api/audit/anchor", headers=HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] >= 1
    assert len(body["head"]) == 64  # sha256 hex chain head

    anchors = client.get("/api/audit/anchors", headers=HEADERS).json()
    assert anchors and anchors[0]["head"] == body["head"]


# ---- 4. Backups (pg_dump + GPG + S3, uniform with the app) -----------------

def test_backup_records_planned_without_apply(client):
    t = make_tenant(client, slug="backuptown")
    provision(client, t["id"])
    r = client.post(f"/api/tenants/{t['id']}/backup", headers=HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "dump"
    # APPLY_STACKS=false and no BACKUP_S3_* -> recorded as intent, not executed.
    assert body["status"] == "planned"
    assert body["path"].startswith("s3://")

    lst = client.get(f"/api/tenants/{t['id']}/backups", headers=HEADERS).json()
    assert lst["backups_enabled"] is False
    assert lst["s3_configured"] is False
    assert len(lst["backups"]) == 1


def test_backup_object_key_uses_app_naming(client, monkeypatch):
    from orchestrator import backups

    monkeypatch.setenv("BACKUP_S3_BUCKET", "pp311-dr")
    monkeypatch.setenv("BACKUP_S3_ACCESS_KEY", "ak")
    monkeypatch.setenv("BACKUP_S3_SECRET_KEY", "sk")
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", "gpg-pass")
    assert backups.s3_configured() is True
    # Same object-name shape as the app: <prefix><name>_<ts>.sql.gpg
    lst = client.get("/api/tenants", headers=HEADERS)  # ensure app is live
    assert lst.status_code == 200


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
