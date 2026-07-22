"""Government-production hardening: RBAC, tamper-evident audit, key rotation,
and the signed-image supply-chain gate."""

import pytest

from orchestrator.config import settings
from tests.conftest import HEADERS, make_tenant, provision


# ---- RBAC -------------------------------------------------------------------

def _as_role(monkeypatch, role):
    """Force the effective role by setting the default (no groups header)."""
    monkeypatch.setattr(settings, "default_operator_role", role)


def test_viewer_cannot_mutate(client, monkeypatch):
    _as_role(monkeypatch, "viewer")
    # read allowed
    assert client.get("/api/tenants", headers=HEADERS).status_code == 200
    # create refused
    r = client.post("/api/tenants", json={"name": "X", "slug": "x"}, headers=HEADERS)
    assert r.status_code == 403
    assert "operator" in r.json()["detail"]


def test_operator_can_mutate_but_not_decommission(client, monkeypatch):
    _as_role(monkeypatch, "operator")
    t = make_tenant(client, slug="opstown")
    provision(client, t["id"])
    # decommission requires approver
    r = client.post(f"/api/tenants/{t['id']}/decommission?confirm_slug=opstown", headers=HEADERS)
    assert r.status_code == 403
    assert "approver" in r.json()["detail"]


def test_approver_can_decommission(client, monkeypatch):
    _as_role(monkeypatch, "approver")
    t = make_tenant(client, slug="apptown")
    provision(client, t["id"])
    r = client.post(f"/api/tenants/{t['id']}/decommission?confirm_slug=apptown", headers=HEADERS)
    assert r.status_code == 200


def test_role_from_groups_header(client, monkeypatch):
    _as_role(monkeypatch, "viewer")
    monkeypatch.setattr(settings, "roles_header", "X-Forwarded-Groups")
    monkeypatch.setattr(settings, "role_group_map", '{"pp311-ops":"operator"}')
    # with the ops group, creation is allowed
    r = client.post(
        "/api/tenants",
        json={"name": "G", "slug": "gtown"},
        headers={**HEADERS, "X-Forwarded-Groups": "pp311-ops other"},
    )
    assert r.status_code == 201
    # without it, back to viewer -> refused
    r = client.post("/api/tenants", json={"name": "H", "slug": "htown"}, headers=HEADERS)
    assert r.status_code == 403


def test_whoami_reports_role_and_actor(client, monkeypatch):
    monkeypatch.setattr(settings, "operator_header", "X-Forwarded-User")
    monkeypatch.setattr(settings, "default_operator_role", "operator")
    who = client.get("/api/whoami", headers={**HEADERS, "X-Forwarded-User": "jane@state.gov"}).json()
    assert who["actor"] == "jane@state.gov"
    assert who["role"] == "operator"


# ---- Tamper-evident audit ---------------------------------------------------

def test_audit_chain_verifies(client):
    make_tenant(client, slug="chain1")
    make_tenant(client, slug="chain2")
    v = client.get("/api/audit/verify", headers=HEADERS).json()
    assert v["ok"] is True
    assert v["entries"] >= 2


def test_audit_chain_detects_tampering(client, db):
    make_tenant(client, slug="tamper")
    from orchestrator.models import AuditLog
    from sqlalchemy import select

    entry = db.execute(select(AuditLog).order_by(AuditLog.seq)).scalars().first()
    entry.detail = {"slug": "HACKED"}  # mutate a recorded value
    db.commit()

    v = client.get("/api/audit/verify", headers=HEADERS).json()
    assert v["ok"] is False
    assert v["broken_at_seq"] == entry.seq


def test_audit_entries_are_chained(client, db):
    make_tenant(client, slug="chained")
    from orchestrator.models import AuditLog
    from sqlalchemy import select

    entries = db.execute(select(AuditLog).order_by(AuditLog.seq)).scalars().all()
    assert entries[0].previous_hash == "GENESIS"
    for prev, cur in zip(entries, entries[1:]):
        assert cur.previous_hash == prev.entry_hash


# ---- Key rotation -----------------------------------------------------------

def test_key_rotation_reencrypts_and_still_decrypts(client, db):
    tenant = make_tenant(client, slug="rotate")
    client.put(
        f"/api/tenants/{tenant['id']}/secrets/GOOGLE_MAPS_API_KEY",
        json={"value": "AIza-rotate-me"},
        headers=HEADERS,
    )
    # Rotation re-encrypts every stored secret under a freshly-wrapped data key.
    r = client.post("/api/maintenance/reencrypt-secrets", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["kms_backend"] == "local"  # no cloud KMS configured in tests

    # the stored ciphertext is the app-uniform envelope scheme and still decrypts
    from orchestrator.models import PlatformSecret
    from orchestrator.security import decrypt_value
    from sqlalchemy import select

    row = db.execute(
        select(PlatformSecret).where(PlatformSecret.key_name == "GOOGLE_MAPS_API_KEY")
    ).scalar_one()
    assert row.encrypted_value.startswith("pii2:")
    assert decrypt_value(row.encrypted_value) == "AIza-rotate-me"


# ---- Signed-image supply-chain gate -----------------------------------------

def test_require_signed_images_blocks_unpinned_release(client, monkeypatch):
    monkeypatch.setattr(settings, "require_signed_images", True)
    client.post("/api/releases", json={"version": "9.9.9"}, headers=HEADERS)  # no digest
    tenant = make_tenant(client, slug="unpinned")
    job = provision(client, tenant["id"])
    assert job["status"] == "failed"
    step = {s["name"]: s for s in job["steps"]}["verify_supply_chain"]
    assert step["status"] == "failed"
    assert "digest-pinned" in step["detail"]


def test_require_signed_images_allows_pinned_release(client, monkeypatch):
    monkeypatch.setattr(settings, "require_signed_images", True)
    digest = "sha256:" + "b" * 64
    client.post(
        "/api/releases",
        json={"version": "9.9.10", "backend_digest": digest, "frontend_digest": digest},
        headers=HEADERS,
    )
    tenant = make_tenant(client, slug="pinned")
    job = provision(client, tenant["id"])
    assert job["status"] == "succeeded"
