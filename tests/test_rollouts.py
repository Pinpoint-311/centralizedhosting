import pytest
from sqlalchemy import select

from orchestrator import rollout as engine
from orchestrator import stack
from orchestrator.config import settings
from orchestrator.models import Release, Rollout, Tenant
from tests.conftest import HEADERS, make_tenant, provision


def _publish(client, version="1.4.0", **extra):
    resp = client.post(
        "/api/releases",
        json={"version": version, "db_revision": "rev_b", "min_db_revision": "rev_a", **extra},
        headers=HEADERS,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _fleet(client, n=3):
    ids = []
    for i in range(n):
        t = make_tenant(client, slug=f"town-{i}", name=f"Town {i}")
        provision(client, t["id"])
        ids.append(t["id"])
    return ids


def test_publish_release_and_duplicate_rejected(client):
    _publish(client)
    resp = client.post("/api/releases", json={"version": "1.4.0"}, headers=HEADERS)
    assert resp.status_code == 409


def test_rollout_requires_active_tenants(client):
    release = _publish(client)
    resp = client.post("/api/rollouts", json={"release_id": release["id"]}, headers=HEADERS)
    assert resp.status_code == 409


def test_dry_run_rollout_canary_then_promote(client):
    release = _publish(client)
    _fleet(client, 3)

    resp = client.post(
        "/api/rollouts", json={"release_id": release["id"], "canary_count": 1}, headers=HEADERS
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "canary_passed"
    phases = {s["phase"] for s in body["steps"]}
    assert phases == {"canary", "fleet"}
    assert [s["status"] for s in body["steps"] if s["phase"] == "canary"] == ["unverified"]
    assert all(s["status"] == "pending" for s in body["steps"] if s["phase"] == "fleet")

    promoted = client.post(f"/api/rollouts/{body['id']}/promote", headers=HEADERS)
    assert promoted.status_code == 200
    assert promoted.json()["status"] == "completed"

    # every town now targets the new version
    for t in client.get("/api/tenants", headers=HEADERS).json():
        assert t["target_version"] == "1.4.0"


def test_only_one_rollout_in_flight(client):
    release = _publish(client)
    _fleet(client, 2)
    first = client.post("/api/rollouts", json={"release_id": release["id"]}, headers=HEADERS)
    assert first.status_code == 201
    second = client.post("/api/rollouts", json={"release_id": release["id"]}, headers=HEADERS)
    assert second.status_code == 409


def test_promote_requires_canary_passed(client):
    release = _publish(client)
    _fleet(client, 2)
    body = client.post(
        "/api/rollouts", json={"release_id": release["id"]}, headers=HEADERS
    ).json()
    client.post(f"/api/rollouts/{body['id']}/rollback", headers=HEADERS)
    resp = client.post(f"/api/rollouts/{body['id']}/promote", headers=HEADERS)
    assert resp.status_code == 409


def _enable_applied_mode(monkeypatch):
    """Pretend stacks really run: apply is a no-op, health comes from a probe.
    Called AFTER fleet provisioning so provisioning itself stays render-only."""
    monkeypatch.setattr(settings, "apply_stacks", True)
    monkeypatch.setattr(stack, "apply_stack", lambda tenant: "ok")
    monkeypatch.setattr(stack, "down_stack", lambda tenant, remove_volumes=False: None)


def _db_fleet(client, db, n=2):
    _fleet(client, n)
    return db.execute(select(Tenant).order_by(Tenant.created_at)).scalars().all()


def test_canary_health_gating_and_auto_rollback(client, db, monkeypatch):
    release_id = _publish(client, version="2.0.0")["id"]
    tenants = _db_fleet(client, db, 2)
    for t in tenants:
        t.running_version = "1.9.0"
    db.commit()
    _enable_applied_mode(monkeypatch)
    release = db.get(Release, release_id)

    # Canary comes up on the wrong version -> auto-rollback
    def bad_probe(tenant):
        return {"version": "1.9.0", "db_revision": "rev_a"}

    obj = engine.create_rollout(db, release, canary_count=1)
    engine.execute_canary(db, obj, actor="test", probe=bad_probe)
    assert obj.status == "rolled_back"
    canary = [s for s in obj.steps if s.phase == "canary"][0]
    assert canary.status in ("failed", "rolled_back")
    assert db.get(Tenant, canary.tenant_id).target_version == "1.9.0"  # restored


def test_canary_passes_with_healthy_probe_and_promotes(client, db, monkeypatch):
    release_id = _publish(client, version="2.0.0")["id"]
    tenants = _db_fleet(client, db, 3)
    for t in tenants:
        t.running_version = "1.9.0"
    db.commit()
    _enable_applied_mode(monkeypatch)
    release = db.get(Release, release_id)

    calls: dict[str, int] = {}

    def good_probe(tenant):
        # first call per tenant is the pre-flight (old compatible revision);
        # the next one is post-upgrade and reports the new build
        n = calls.get(tenant.id, 0)
        calls[tenant.id] = n + 1
        if n == 0:
            return {"version": "1.9.0", "db_revision": "rev_a"}
        return {"version": "2.0.0", "db_revision": "rev_b"}

    obj = engine.create_rollout(db, release, canary_count=1)
    engine.execute_canary(db, obj, actor="test", probe=good_probe)
    assert obj.status == "canary_passed"
    engine.promote(db, obj, actor="test", probe=good_probe)
    assert obj.status == "completed"
    for t in db.execute(select(Tenant)).scalars():
        assert t.running_version == "2.0.0"


def test_preflight_blocks_incompatible_db_revision(client, db, monkeypatch):
    release_id = _publish(client, version="2.0.0")["id"]
    _db_fleet(client, db, 1)
    _enable_applied_mode(monkeypatch)
    release = db.get(Release, release_id)

    def ancient_probe(tenant):
        return {"version": "1.0.0", "db_revision": "rev_ancient"}

    obj = engine.create_rollout(db, release, canary_count=1)
    engine.execute_canary(db, obj, actor="test", probe=ancient_probe)
    assert obj.status == "rolled_back"
    canary = [s for s in obj.steps if s.phase == "canary"][0]
    assert "compatibility window" in (canary.detail or "")


def test_rollout_lifecycle_is_audited(client):
    release = _publish(client)
    _fleet(client, 1)
    client.post("/api/rollouts", json={"release_id": release["id"]}, headers=HEADERS)
    actions = {e["action"] for e in client.get("/api/audit", headers=HEADERS).json()}
    assert {"release.published", "rollout.canary_started", "rollout.canary_passed"} <= actions
