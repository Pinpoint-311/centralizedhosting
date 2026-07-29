"""Applying an update to a town: migrate, recreate, keep the data.

The rollout engine always verified that migrations had landed but nothing ever
ran them, so a release carrying a schema change failed its own canary gate.
These cover the step that closes that, and the invariants around it.
"""

import pytest

from orchestrator import migrator, rollout as engine, stack
from orchestrator.config import settings
from orchestrator.models import Release, Tenant
from tests.conftest import HEADERS, make_tenant, provision

HEAD = "d4e5f6a7b8c9"
PREV = "c3d4e5f6a7b8"


@pytest.fixture()
def town(client, db):
    t = make_tenant(client, slug="migratetown", name="Migrate Town")
    provision(client, t["id"])
    tenant = db.get(Tenant, t["id"])
    tenant.running_version = "1.2.0"
    db.commit()
    return tenant


@pytest.fixture()
def release(db):
    r = Release(version="1.3.0", backend_image="img/b", frontend_image="img/f",
                backend_digest="sha256:" + "a" * 64,
                frontend_digest="sha256:" + "b" * 64,
                db_revision=HEAD, min_db_revision=PREV)
    db.add(r)
    db.commit()
    return r


@pytest.fixture()
def applied(monkeypatch):
    """Pretend the stacks really run, recording every compose invocation."""
    calls: list[list[str]] = []

    def fake_compose(tenant, *args, timeout=0):
        calls.append(list(args))
        import subprocess

        out = ""
        if args[:1] == ("exec",):
            # schema_state probes: tracked, sitting on the previous revision
            sql = args[-1]
            out = "t" if "to_regclass" in sql else PREV
        return subprocess.CompletedProcess(args, 0, out, "")

    monkeypatch.setattr(settings, "apply_stacks", True)
    monkeypatch.setattr(migrator, "_compose", fake_compose)
    monkeypatch.setattr(stack, "apply_stack", lambda tenant: "recreated")
    return calls


def _probe_factory(revisions):
    """Health probe returning queued (version, db_revision) pairs per call."""
    seen: dict[str, int] = {}

    def probe(tenant):
        n = seen.get(tenant.id, 0)
        seen[tenant.id] = n + 1
        version, revision = revisions[min(n, len(revisions) - 1)]
        return {"version": version, "db_revision": revision}

    return probe


def test_upgrade_runs_alembic_before_the_new_app_serves(client, db, town, release, applied):
    """Migrate first, then recreate. The reverse order has a window where the
    new code queries columns that do not exist yet."""
    probe = _probe_factory([("1.2.0", PREV), ("1.3.0", HEAD)])
    obj = engine.create_rollout(db, release, canary_count=1)
    engine.execute_canary(db, obj, actor="test", probe=probe)

    assert obj.status == "canary_passed", obj.error
    upgrade = [c for c in applied if c[:3] == ["run", "--rm", "-T"]]
    assert upgrade and upgrade[0][-2:] == ["upgrade", "head"]

    step = obj.steps[0]
    assert "migrated" in (step.detail or "")


def test_an_upgrade_never_destroys_the_towns_data(client, db, town, release, applied):
    """The one non-negotiable. Resident data and town config live in named
    volumes; `docker compose down` or any `--volumes` flag in the upgrade path
    would take them with it."""
    probe = _probe_factory([("1.2.0", PREV), ("1.3.0", HEAD)])
    obj = engine.create_rollout(db, release, canary_count=1)
    engine.execute_canary(db, obj, actor="test", probe=probe)

    for call in applied:
        assert "down" not in call, f"upgrade issued a destructive compose command: {call}"
        assert "--volumes" not in call and "-v" not in call
        assert "rm" not in call or call[:2] == ["run", "--rm"]  # one-shot container only


def test_config_and_secrets_survive_the_upgrade(client, db, town, release, applied):
    """The stack is re-rendered on every upgrade. Re-rendering must reproduce
    the same secrets, not mint new ones — a rotated SECRET_KEY would invalidate
    every session and make the town's encrypted data unreadable."""
    env_before = (stack.tenant_dir(town) / ".env").read_text()

    probe = _probe_factory([("1.2.0", PREV), ("1.3.0", HEAD)])
    obj = engine.create_rollout(db, release, canary_count=1)
    engine.execute_canary(db, obj, actor="test", probe=probe)

    env_after = (stack.tenant_dir(town) / ".env").read_text()

    def secrets(text):
        return {line.split("=", 1)[0]: line.split("=", 1)[1]
                for line in text.splitlines()
                if "=" in line and not line.startswith("#")}

    before, after = secrets(env_before), secrets(env_after)
    for key in ("SECRET_KEY", "DB_PASSWORD", "PROVISIONING_TOKEN"):
        if key in before:
            assert after[key] == before[key], f"{key} changed across an upgrade"


def test_a_failed_migration_fails_the_step_and_rolls_back(client, db, town, release, applied,
                                                          monkeypatch):
    """A half-applied schema is the worst outcome, so a migration failure stops
    the rollout rather than starting the new build on top of it."""
    def boom(tenant):
        raise migrator.MigrationError("relation already exists")

    monkeypatch.setattr(migrator, "run_migrations", boom)
    probe = _probe_factory([("1.2.0", PREV)])
    obj = engine.create_rollout(db, release, canary_count=1)
    engine.execute_canary(db, obj, actor="test", probe=probe)

    assert obj.status == "rolled_back"
    step = obj.steps[0]
    assert "relation already exists" in (step.detail or "")
    assert db.get(Tenant, step.tenant_id).target_version == "1.2.0"  # restored


def test_migration_is_skipped_when_the_town_is_already_on_the_release_schema(
    client, db, town, release, applied
):
    """alembic upgrade is idempotent, but skipping the work when the revision
    already matches keeps a no-op rollout from touching the database at all."""
    probe = _probe_factory([("1.3.0", HEAD)])
    obj = engine.create_rollout(db, release, canary_count=1)
    engine.execute_canary(db, obj, actor="test", probe=probe)

    assert not [c for c in applied if c[-2:] == ["upgrade", "head"]]


def test_untracked_schema_refuses_rather_than_guessing_a_baseline(monkeypatch, db, town):
    """The app builds tables with create_all and its Alembic chain is
    supplemental, so a town can have a full schema and no alembic_version row.
    Replaying the chain would collide; stamping a guess would record a baseline
    nobody verified. Refuse and name the fix."""
    monkeypatch.setattr(settings, "apply_stacks", True)

    def fake_compose(tenant, *args, timeout=0):
        import subprocess

        out = ""
        if args[:1] == ("exec",):
            sql = args[-1]
            out = "f" if "to_regclass" in sql else "42"  # untracked, 42 tables
        return subprocess.CompletedProcess(args, 0, out, "")

    monkeypatch.setattr(migrator, "_compose", fake_compose)
    with pytest.raises(migrator.MigrationError, match="predates migration tracking"):
        migrator.run_migrations(town)


def test_empty_schema_is_left_to_the_app_to_create(monkeypatch, db, town):
    monkeypatch.setattr(settings, "apply_stacks", True)

    def fake_compose(tenant, *args, timeout=0):
        import subprocess

        out = ""
        if args[:1] == ("exec",):
            out = "f" if "to_regclass" in args[-1] else "0"
        return subprocess.CompletedProcess(args, 0, out, "")

    monkeypatch.setattr(migrator, "_compose", fake_compose)
    assert "no schema yet" in migrator.run_migrations(town)


def test_schema_endpoints_report_and_adopt(client, db, town, monkeypatch):
    monkeypatch.setattr(settings, "apply_stacks", True)
    state = {"tracked": "f"}

    def fake_compose(tenant, *args, timeout=0):
        import subprocess

        out = ""
        if args[:1] == ("exec",):
            out = state["tracked"] if "to_regclass" in args[-1] else (
                PREV if state["tracked"] == "t" else "42")
        return subprocess.CompletedProcess(args, 0, out, "")

    monkeypatch.setattr(migrator, "_compose", fake_compose)

    r = client.get(f"/api/tenants/{town.id}/schema", headers=HEADERS).json()
    assert r["state"] == migrator.UNTRACKED

    # Adoption is guarded by the slug, like decommission — it is not undoable.
    bad = client.post(f"/api/tenants/{town.id}/schema/adopt",
                      json={"revision": PREV, "confirm_slug": "wrong"}, headers=HEADERS)
    assert bad.status_code == 400

    ok = client.post(f"/api/tenants/{town.id}/schema/adopt",
                     json={"revision": PREV, "confirm_slug": town.slug}, headers=HEADERS)
    assert ok.status_code == 200 and ok.json()["revision"] == PREV

    actions = {e["action"] for e in client.get("/api/audit", headers=HEADERS).json()}
    assert "tenant.schema_adopted" in actions


def test_pre_migration_backup_failure_stops_the_upgrade(client, db, town, monkeypatch):
    """Migrating without a restore point is how a bad migration becomes
    permanent data loss."""
    monkeypatch.setattr(settings, "apply_stacks", True)
    monkeypatch.setattr(settings, "backups_enabled", True)
    monkeypatch.setattr(settings, "backup_before_migrate", True)

    from orchestrator import backups
    from orchestrator.models import BackupRecord

    def failed_backup(db_, tenant, actor="auto-backup"):
        return BackupRecord(tenant_id=tenant.id, status="failed", detail="S3 unreachable")

    monkeypatch.setattr(backups, "run_base_backup", failed_backup)
    with pytest.raises(migrator.MigrationError, match="refusing to migrate"):
        migrator.backup_before_migration(db, town)


def test_apply_stack_recreates_containers_without_removing_volumes(monkeypatch, town):
    """`--remove-orphans` clears containers for services a release dropped;
    it must never be accompanied by a volume flag."""
    seen = {}

    def fake_run(cmd, **kwargs):
        import subprocess

        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(stack.subprocess, "run", fake_run)
    stack.apply_stack(town)
    assert "up" in seen["cmd"] and "--remove-orphans" in seen["cmd"]
    assert "--volumes" not in seen["cmd"] and "down" not in seen["cmd"]
