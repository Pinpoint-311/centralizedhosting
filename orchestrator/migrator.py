"""Run a town's database migrations during an upgrade.

The rollout engine has always *verified* migrations ("does the town now report
the release's db_revision?") but nothing ever *ran* them, so any release carrying
a schema change failed its own canary gate. This module is that missing step.

Ordering is the whole design:

1. back up  — a schema change is the one upgrade action that is not trivially
   reversible, so the snapshot is taken while the old schema is still intact.
2. pull     — fetch the new images before stopping anything, so a registry
   failure costs nothing.
3. migrate  — ``alembic upgrade head`` in a one-shot container built from the
   NEW image, against the running database, before the new app serves traffic.
4. recreate — start the new containers.

Migrating before the new backend is up is deliberate. Expand-style migrations
are compatible with the old code (that is what ``min_db_revision`` asserts), so
running them first means the new code never sees a schema older than it expects.
The reverse order has a window where new code queries columns that do not exist.

Everything here is a no-op unless ``APPLY_STACKS=true`` — in render-only mode
there are no containers to migrate.
"""

import logging
import subprocess

from orchestrator.config import settings
from orchestrator.models import Tenant
from orchestrator.stack import tenant_dir

logger = logging.getLogger(__name__)


class MigrationError(RuntimeError):
    """A migration command failed. The caller rolls the step back."""


def _compose(tenant: Tenant, *args: str, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "--project-name", f"pp311-{tenant.slug}", *args],
        cwd=tenant_dir(tenant),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def pull_images(tenant: Tenant) -> str:
    """Fetch the pinned images ahead of touching the running stack.

    Without this, a registry outage is discovered halfway through recreating
    containers, with the town already down.
    """
    result = _compose(tenant, "pull", "--quiet", timeout=settings.migration_timeout_seconds)
    if result.returncode != 0:
        raise MigrationError(f"image pull failed: {(result.stderr or result.stdout)[-1500:]}")
    return "images pulled"


TRACKED = "tracked"        # alembic_version present — a normal upgrade
EMPTY = "empty"            # no application tables yet — nothing to migrate
UNTRACKED = "untracked"    # tables exist but Alembic has never run here


def _psql(tenant: Tenant, sql: str, timeout: int = 120) -> str:
    """One scalar query against the town's own database.

    Runs inside the db container, so the credentials never leave it — the
    container already has POSTGRES_USER/POSTGRES_DB in its environment.
    """
    result = _compose(
        tenant, "exec", "-T", "db", "sh", "-c",
        f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "{sql}"',
        timeout=timeout,
    )
    if result.returncode != 0:
        raise MigrationError(
            f"could not query the town database: {(result.stderr or result.stdout)[-800:]}")
    return result.stdout.strip()


def schema_state(tenant: Tenant) -> tuple[str, str | None]:
    """Classify the town's schema: (state, current_revision).

    Mirrors the panel's own ``db.init_db`` triage, for the same reason — the
    three cases need three different actions and conflating them corrupts the
    migration baseline.
    """
    tracked = _psql(tenant, "SELECT to_regclass('public.alembic_version') IS NOT NULL")
    if tracked.lower().startswith("t"):
        rev = _psql(tenant, "SELECT version_num FROM alembic_version LIMIT 1")
        return TRACKED, (rev or None)

    n_tables = _psql(
        tenant,
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'",
    )
    return (EMPTY if n_tables in ("", "0") else UNTRACKED), None


def stamp_revision(tenant: Tenant, revision: str) -> str:
    """``alembic stamp`` — record a baseline without running any migration.

    Only ever called from the explicit operator adoption action. Stamping is
    irreversible in effect: every later migration builds on the claim that this
    revision describes the schema, so it is a human decision, not a fallback.
    """
    result = _compose(
        tenant, "run", "--rm", "-T", "backend", "alembic", "stamp", revision,
        timeout=settings.migration_timeout_seconds,
    )
    if result.returncode != 0:
        raise MigrationError(
            f"alembic stamp failed: {(result.stderr or result.stdout)[-1500:]}")
    return f"stamped at {revision}"


def run_migrations(tenant: Tenant) -> str:
    """Bring the town's schema to head, or refuse and say why.

    The app builds its tables with ``Base.metadata.create_all`` at startup and
    keeps a *supplemental* Alembic chain whose base revision only adds a
    translations table. So a town's database can be in three states, and only one
    of them is a plain upgrade:

    * **tracked** — ``alembic upgrade head``. The normal path.
    * **empty** — nothing to migrate; the app creates its tables when it boots
      and adoption happens on the next pass, once there is a schema to describe.
    * **untracked** — tables exist, Alembic never ran. Replaying the chain here
      would fail (or worse, half-apply) against columns that already exist, and
      stamping a guessed revision would record a baseline nobody verified. This
      refuses, and an operator adopts the town deliberately.
    """
    started = _compose(tenant, "up", "-d", "--wait", "db", timeout=300)
    if started.returncode != 0:
        raise MigrationError(
            f"database did not come up for migration: {(started.stderr or '')[-1500:]}")

    state, revision = schema_state(tenant)
    if state == EMPTY:
        return "no schema yet — the app creates its tables on first boot"
    if state == UNTRACKED:
        raise MigrationError(
            f"{tenant.slug} has tables but no alembic_version row, so its schema "
            "predates migration tracking. Replaying the chain would collide with "
            "columns that already exist. Adopt it first with POST /api/tenants/"
            f"{tenant.id}/schema/adopt naming the revision its schema matches."
        )

    result = _compose(
        tenant, "run", "--rm", "-T", "backend",
        "alembic", "upgrade", "head",
        timeout=settings.migration_timeout_seconds,
    )
    if result.returncode != 0:
        raise MigrationError(
            f"alembic upgrade failed from {revision}: "
            f"{(result.stderr or result.stdout)[-1500:]}")
    return (result.stdout or f"upgraded from {revision}").strip()[-1500:]


def recreate_services(tenant: Tenant) -> str:
    """Bring every service in the town onto the new images.

    ``up -d`` recreates exactly the containers whose image or configuration
    changed and leaves the rest running — so backend, worker and frontend are
    replaced while Postgres and Redis keep serving. Named volumes are untouched
    by definition: this never issues ``down``, and never ``--volumes``. That is
    what keeps resident data and the town's configuration across an upgrade.

    Delegates to ``stack.apply_stack`` so there is exactly one place that starts
    a town's containers, whether it is being provisioned or upgraded.
    """
    from orchestrator import stack

    try:
        return stack.apply_stack(tenant)
    except RuntimeError as exc:
        raise MigrationError(str(exc)) from exc


def backup_before_migration(db, tenant: Tenant) -> str:
    """Snapshot the town before its schema changes.

    Best-effort by configuration, fail-closed by intent: if backups are switched
    on and the snapshot fails, that is reported as an error and the caller
    aborts. Migrating with a broken backup pipeline is how a bad migration
    becomes unrecoverable data loss.
    """
    if not settings.backup_before_migrate:
        return "pre-migration backup disabled (BACKUP_BEFORE_MIGRATE=false)"
    if not settings.backups_enabled:
        return "no pre-migration backup — BACKUPS_ENABLED is false"

    from orchestrator import backups

    record = backups.run_base_backup(db, tenant, actor="pre-migration")
    if record.status == "failed":
        raise MigrationError(
            f"pre-migration backup failed ({record.detail}); refusing to migrate "
            "without a restore point"
        )
    if record.status == "planned":
        # Recorded as intent only (no S3 configured) — say so rather than let
        # "backed up" imply a restore point that does not exist.
        return f"no real backup taken: {record.detail}"
    return f"backed up to {record.path} ({record.size_bytes} bytes)"


def reload_edge_proxy() -> str | None:
    """Reload the host front proxy so changed town site blocks take effect.

    Configured as a command because the proxy lives outside the town stacks and
    every host runs it differently. Never fatal — a stale proxy config is a
    routing problem to fix, not a reason to fail an otherwise healthy upgrade.
    """
    command = settings.caddy_reload_command.strip()
    if not command:
        return None
    import shlex

    try:
        result = subprocess.run(
            shlex.split(command), capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("edge proxy reload failed to start: %s", exc)
        return f"edge proxy reload failed: {exc}"
    if result.returncode != 0:
        logger.warning("edge proxy reload exited %s", result.returncode)
        return f"edge proxy reload exited {result.returncode}: {(result.stderr or '')[-300:]}"
    return "edge proxy reloaded"
