"""B3 — release management: canary rollouts with migration gating + rollback.

Flow (plan B3): org publishes a versioned image → panel schedules a canary
rollout across the fleet → watches the A3 health/version stamp
({version, git_sha, db_revision, min_db_revision}) → auto-rolls-back on
failure → enforces DB-revision compatibility before promoting.

Compatibility gate (expand/contract rule from plan A3): a release declares
`db_revision` (what its migrations produce) and `min_db_revision` (the oldest
schema the build runs against). Before upgrading a town, its observed
db_revision must be one of those two; after upgrading, the town must report
the release's version and db_revision to count as healthy.
"""

import logging
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator import audit, stack
from orchestrator.app_client import client_for_tenant
from orchestrator.config import settings
from orchestrator.models import (
    Release,
    Rollout,
    RolloutStatus,
    RolloutStep,
    Tenant,
    TenantStatus,
    utcnow,
)

logger = logging.getLogger(__name__)

# probe(tenant) -> A3 health dict; raises when the town is unreachable.
HealthProbe = Callable[[Tenant], dict]


def default_probe(tenant: Tenant) -> dict:
    client = client_for_tenant(tenant)
    try:
        return client.health_version()
    finally:
        client.close()


def create_rollout(db: Session, release: Release, canary_count: int | None = None) -> Rollout:
    tenants = (
        db.execute(
            select(Tenant)
            .where(Tenant.status == TenantStatus.ACTIVE)
            .order_by(Tenant.created_at)
        )
        .scalars()
        .all()
    )
    if not tenants:
        raise ValueError("no active tenants to roll out to")

    n_canary = min(canary_count or settings.canary_count, len(tenants))
    rollout = Rollout(release_id=release.id, canary_count=n_canary)
    db.add(rollout)
    db.flush()
    for position, tenant in enumerate(tenants):
        db.add(
            RolloutStep(
                rollout_id=rollout.id,
                tenant_id=tenant.id,
                position=position,
                phase="canary" if position < n_canary else "fleet",
                previous_version=tenant.running_version or tenant.target_version,
            )
        )
    db.flush()
    return rollout


def _secrets_bundle(db: Session, tenant: Tenant) -> dict[str, str]:
    from orchestrator.provisioner import _secrets_bundle as bundle

    return bundle(db, tenant)


def _precheck_compatibility(release: Release, tenant: Tenant, probe: HealthProbe) -> str | None:
    """Return an error string when the town's schema is outside the release's
    declared compatibility window; None when OK or unverifiable."""
    if not release.min_db_revision:
        return None
    try:
        health = probe(tenant)
    except Exception:
        return None if not settings.apply_stacks else "town unreachable for pre-flight check"
    observed = health.get("db_revision")
    if observed and observed not in {release.min_db_revision, release.db_revision}:
        return (
            f"db_revision {observed} outside compatibility window "
            f"[{release.min_db_revision} .. {release.db_revision}]"
        )
    return None


def _upgrade_step(db: Session, step: RolloutStep, release: Release, probe: HealthProbe) -> bool:
    """Upgrade one town and verify. Returns True when the step is healthy
    (or unverifiable in render-only mode)."""
    tenant = step.tenant
    step.status = "upgrading"

    incompat = _precheck_compatibility(release, tenant, probe)
    if incompat:
        step.status = "failed"
        step.detail = f"pre-flight: {incompat}"
        return False

    tenant.target_version = release.version
    stack.render_stack(
        tenant,
        _secrets_bundle(db, tenant),
        release.version,
        backend_digest=release.backend_digest,
        frontend_digest=release.frontend_digest,
    )
    if not settings.apply_stacks:
        step.status = "unverified"
        step.detail = "stack re-rendered; apply disabled so health not verified"
        return True
    try:
        stack.apply_stack(tenant)
        health = probe(tenant)
    except Exception as exc:  # noqa: BLE001
        step.status = "failed"
        step.detail = f"upgrade/probe failed: {exc}"[:2000]
        return False

    if health.get("version") != release.version:
        step.status = "failed"
        step.detail = f"reports version {health.get('version')!r}, expected {release.version!r}"
        return False
    if release.db_revision and health.get("db_revision") != release.db_revision:
        step.status = "failed"
        step.detail = (
            f"db_revision {health.get('db_revision')!r} != release {release.db_revision!r} "
            "(migrations did not land)"
        )
        return False

    step.status = "healthy"
    step.detail = f"healthy on {release.version}"
    tenant.running_version = release.version
    return True


def _rollback_step(db: Session, step: RolloutStep) -> None:
    tenant = step.tenant
    previous = step.previous_version
    if not previous:
        step.detail = ((step.detail or "") + " | no previous version recorded, left as-is").strip()
        return
    tenant.target_version = previous
    from orchestrator.provisioner import render_for_tenant

    render_for_tenant(db, tenant, previous)
    if settings.apply_stacks:
        try:
            stack.apply_stack(tenant)
            tenant.running_version = previous
        except Exception as exc:  # noqa: BLE001
            logger.error("rollback apply failed for %s: %s", tenant.slug, exc)
            step.detail = ((step.detail or "") + f" | ROLLBACK APPLY FAILED: {exc}")[:2000]
            return
    step.status = "rolled_back"


def _run_phase(
    db: Session, rollout: Rollout, release: Release, phase: str, probe: HealthProbe, actor: str
) -> bool:
    """Upgrade every step in a phase; on any failure, roll back that phase's
    already-upgraded steps and mark the rollout rolled_back."""
    phase_steps = [s for s in rollout.steps if s.phase == phase]
    for step in phase_steps:
        ok = _upgrade_step(db, step, release, probe)
        db.flush()
        if ok:
            continue
        audit.record(
            db, actor, "rollout.step_failed", step.tenant_id,
            rollout_id=rollout.id, version=release.version, detail=step.detail,
        )
        for done in phase_steps:
            # the failed step itself may have re-rendered before failing —
            # restore it along with its already-upgraded peers
            if done is step or done.status in ("healthy", "unverified"):
                _rollback_step(db, done)
        rollout.status = RolloutStatus.ROLLED_BACK
        rollout.error = f"{phase} failed on {step.tenant.slug}: {step.detail}"
        rollout.finished_at = utcnow()
        audit.record(db, actor, "rollout.rolled_back", None, rollout_id=rollout.id, phase=phase)
        db.commit()
        return False
    return True


def execute_canary(db: Session, rollout: Rollout, actor: str, probe: HealthProbe | None = None) -> Rollout:
    probe = probe or default_probe
    release = rollout.release
    rollout.status = RolloutStatus.CANARY
    audit.record(db, actor, "rollout.canary_started", None,
                 rollout_id=rollout.id, version=release.version)
    if _run_phase(db, rollout, release, "canary", probe, actor):
        rollout.status = RolloutStatus.CANARY_PASSED
        audit.record(db, actor, "rollout.canary_passed", None, rollout_id=rollout.id)
        db.commit()
    return rollout


def promote(db: Session, rollout: Rollout, actor: str, probe: HealthProbe | None = None) -> Rollout:
    if rollout.status != RolloutStatus.CANARY_PASSED:
        raise ValueError(f"rollout must be canary_passed to promote (is {rollout.status})")
    probe = probe or default_probe
    release = rollout.release
    rollout.status = RolloutStatus.PROMOTING
    audit.record(db, actor, "rollout.promotion_started", None, rollout_id=rollout.id)
    if _run_phase(db, rollout, release, "fleet", probe, actor):
        rollout.status = RolloutStatus.COMPLETED
        rollout.finished_at = utcnow()
        audit.record(db, actor, "rollout.completed", None,
                     rollout_id=rollout.id, version=release.version)
        db.commit()
    return rollout


def rollback(db: Session, rollout: Rollout, actor: str) -> Rollout:
    """Operator-initiated rollback of everything this rollout upgraded."""
    for step in rollout.steps:
        if step.status in ("healthy", "unverified"):
            _rollback_step(db, step)
    rollout.status = RolloutStatus.ROLLED_BACK
    rollout.finished_at = utcnow()
    audit.record(db, actor, "rollout.rolled_back", None, rollout_id=rollout.id, manual=True)
    db.commit()
    return rollout
