"""B2 — the provisioner.

Per town, in the plan's order: create DB → generate SECRET_KEY → create/assign
KMS key → allocate storage bucket → set DNS + request TLS → deploy app image
@ version → call the app's provisioning API (A4) → surface the one-time
onboarding link. Idempotent and re-runnable: every step checks world state
first and reports "skipped" when its work already exists.

Cloud-specific pieces (KMS key creation, bucket creation, DNS records) are
recorded as resource references here; wiring them to a real GCP/Azure/route53
driver replaces the body of the matching step without touching the pipeline.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator import audit, stack
from orchestrator.app_client import client_for_tenant
from orchestrator.config import settings
from orchestrator.models import (
    PlatformSecret,
    ProvisionJob,
    ProvisionStep,
    Release,
    Tenant,
    TenantStatus,
    utcnow,
)
from orchestrator.security import decrypt_value, encrypt_value, generate_secret

logger = logging.getLogger(__name__)

DONE = "done"
SKIPPED = "skipped"


def get_platform_secret(db: Session, tenant_id: str, key: str) -> str | None:
    row = db.execute(
        select(PlatformSecret).where(
            PlatformSecret.tenant_id == tenant_id, PlatformSecret.key_name == key
        )
    ).scalar_one_or_none()
    return decrypt_value(row.encrypted_value) if row else None


def set_platform_secret(db: Session, tenant_id: str, key: str, value: str) -> None:
    row = db.execute(
        select(PlatformSecret).where(
            PlatformSecret.tenant_id == tenant_id, PlatformSecret.key_name == key
        )
    ).scalar_one_or_none()
    if row:
        row.encrypted_value = encrypt_value(value)
    else:
        db.add(PlatformSecret(tenant_id=tenant_id, key_name=key, encrypted_value=encrypt_value(value)))
    db.flush()


def _ensure_secret(db: Session, tenant: Tenant, key: str) -> tuple[str, bool]:
    existing = get_platform_secret(db, tenant.id, key)
    if existing:
        return existing, False
    value = generate_secret()
    set_platform_secret(db, tenant.id, key, value)
    return value, True


def get_state_credential(db: Session, key: str) -> str | None:
    from orchestrator.models import StateCredential

    row = db.execute(
        select(StateCredential).where(StateCredential.key_name == key)
    ).scalar_one_or_none()
    return decrypt_value(row.encrypted_value) if row else None


def set_state_credential(db: Session, key: str, value: str) -> None:
    from orchestrator.models import StateCredential

    row = db.execute(
        select(StateCredential).where(StateCredential.key_name == key)
    ).scalar_one_or_none()
    if row:
        row.encrypted_value = encrypt_value(value)
    else:
        db.add(StateCredential(key_name=key, encrypted_value=encrypt_value(value)))
    db.flush()


def _secrets_bundle(db: Session, tenant: Tenant) -> dict[str, str]:
    """Everything injected into the town's env: per-tenant platform secrets
    (infra + state_per_town service keys) plus the shared-pool values for any
    service this town assigned to ``state_shared``."""
    from orchestrator.key_catalog import shared_keys

    rows = db.execute(
        select(PlatformSecret).where(PlatformSecret.tenant_id == tenant.id)
    ).scalars().all()
    bundle = {r.key_name: decrypt_value(r.encrypted_value) for r in rows}

    for key in shared_keys(tenant.key_assignments):
        value = get_state_credential(db, key)
        if value:
            bundle[key] = value
    return bundle


def release_for_version(db: Session, version: str) -> Release | None:
    return db.execute(
        select(Release).where(Release.version == version)
    ).scalar_one_or_none()


def _target_version(db: Session, tenant: Tenant) -> str:
    if tenant.target_version:
        return tenant.target_version
    latest = db.execute(
        select(Release).order_by(Release.published_at.desc())
    ).scalars().first()
    return latest.version if latest else "latest"


def render_for_tenant(db: Session, tenant: Tenant, version: str) -> None:
    """Render a town's stack, pinning image digests from the matching Release
    when it declares them (government-correct supply-chain posture)."""
    rel = release_for_version(db, version)
    stack.render_stack(
        tenant,
        _secrets_bundle(db, tenant),
        version,
        backend_digest=rel.backend_digest if rel else None,
        frontend_digest=rel.frontend_digest if rel else None,
    )


# --------------------------------------------------------------------- steps

def _step_allocate_database(db: Session, tenant: Tenant, ctx: dict) -> tuple[str, str]:
    # MVP compose shape: each town runs its own PostGIS container, so
    # "create DB" = name it + mint its password. A shared-cluster driver
    # would issue CREATE DATABASE / CREATE ROLE here instead.
    created = False
    if not tenant.db_name:
        tenant.db_name = f"pp311_{tenant.slug}".replace("-", "_")[:63]
        created = True
    _, pw_created = _ensure_secret(db, tenant, "DB_PASSWORD")
    if created or pw_created:
        return DONE, f"database {tenant.db_name} allocated"
    return SKIPPED, f"database {tenant.db_name} already allocated"


def _step_generate_secret_key(db: Session, tenant: Tenant, ctx: dict) -> tuple[str, str]:
    _, created = _ensure_secret(db, tenant, "SECRET_KEY")
    return (DONE, "SECRET_KEY generated") if created else (SKIPPED, "SECRET_KEY already present")


def _step_generate_provisioning_token(db: Session, tenant: Tenant, ctx: dict) -> tuple[str, str]:
    _, created = _ensure_secret(db, tenant, "PROVISIONING_TOKEN")
    return (DONE, "PROVISIONING_TOKEN generated") if created else (SKIPPED, "already present")


def _step_assign_kms_key(db: Session, tenant: Tenant, ctx: dict) -> tuple[str, str]:
    # Per-town key in the state's shared KMS (plan open decision #1). The ref
    # is what enables crypto-shred on decommission: destroy this key and every
    # DEK the town's envelope encryption wrapped with it dies too.
    if tenant.kms_key_ref:
        return SKIPPED, f"key already assigned: {tenant.kms_key_ref}"
    tenant.kms_key_ref = f"kms://state-shared/keyRings/pinpoint311/cryptoKeys/{tenant.slug}"
    return DONE, f"per-town key assigned: {tenant.kms_key_ref}"


def _step_allocate_storage(db: Session, tenant: Tenant, ctx: dict) -> tuple[str, str]:
    if tenant.storage_bucket:
        return SKIPPED, f"bucket already allocated: {tenant.storage_bucket}"
    tenant.storage_bucket = f"pp311-{tenant.slug}-uploads"
    return DONE, f"per-town bucket allocated: {tenant.storage_bucket}"


def _step_allocate_ports(db: Session, tenant: Tenant, ctx: dict) -> tuple[str, str]:
    if tenant.backend_port and tenant.frontend_port:
        return SKIPPED, f"ports {tenant.backend_port}/{tenant.frontend_port} already allocated"
    used = set(
        db.execute(select(Tenant.backend_port).where(Tenant.backend_port.is_not(None))).scalars()
    )
    offset = 0
    while settings.base_backend_port + offset in used:
        offset += 1
    tenant.backend_port = settings.base_backend_port + offset
    tenant.frontend_port = settings.base_frontend_port + offset
    return DONE, f"loopback ports {tenant.backend_port}/{tenant.frontend_port} allocated"


def _step_configure_dns(db: Session, tenant: Tenant, ctx: dict) -> tuple[str, str]:
    # DNS + TLS intent record. Wildcard *.BASE_DOMAIN covers subdomains; a
    # custom domain needs its own record + on-demand ACME at the host Caddy.
    host = tenant.external_host
    if tenant.custom_domain:
        return DONE, f"custom domain {host}: CNAME to managed host + on-demand ACME required"
    return DONE, f"{host} served via wildcard *.{settings.base_domain} DNS + TLS"


def _step_render_stack(db: Session, tenant: Tenant, ctx: dict) -> tuple[str, str]:
    version = _target_version(db, tenant)
    tenant.target_version = version
    render_for_tenant(db, tenant, version)
    return DONE, f"compose stack rendered at {stack.tenant_dir(tenant)} (version {version})"


def _step_apply_stack(db: Session, tenant: Tenant, ctx: dict) -> tuple[str, str]:
    if not settings.apply_stacks:
        return SKIPPED, "apply disabled (APPLY_STACKS=false) — stack rendered only"
    output = stack.apply_stack(tenant)
    tenant.running_version = tenant.target_version
    return DONE, f"stack up: {output.strip()[:500] or 'ok'}"


def _step_app_bootstrap(db: Session, tenant: Tenant, ctx: dict) -> tuple[str, str]:
    if not settings.apply_stacks:
        return SKIPPED, "apply disabled — town bootstrap deferred until stack runs"
    client = ctx.get("client") or client_for_tenant(
        tenant, provisioning_token=get_platform_secret(db, tenant.id, "PROVISIONING_TOKEN")
    )
    try:
        result = client.bootstrap(
            township_name=tenant.name,
            domain=tenant.external_host,
            admin_email=tenant.contact_email or "",
        )
    finally:
        if not ctx.get("client"):
            client.close()
    ctx["onboarding_link"] = result.get("onboarding_link")
    return DONE, "township bootstrapped via provisioning API"


def _step_onboarding_link(db: Session, tenant: Tenant, ctx: dict) -> tuple[str, str]:
    link = ctx.get("onboarding_link")
    if not link:
        return SKIPPED, "no onboarding link (bootstrap deferred)"
    # Email delivery is a driver seam; until wired, the link is surfaced on
    # the job record for the operator to hand to the town admin.
    ctx["record_link"] = True
    return DONE, f"one-time onboarding link ready for {tenant.contact_email or 'town admin'}"


PIPELINE = [
    ("allocate_database", _step_allocate_database),
    ("generate_secret_key", _step_generate_secret_key),
    ("generate_provisioning_token", _step_generate_provisioning_token),
    ("assign_kms_key", _step_assign_kms_key),
    ("allocate_storage", _step_allocate_storage),
    ("allocate_ports", _step_allocate_ports),
    ("configure_dns", _step_configure_dns),
    ("render_stack", _step_render_stack),
    ("apply_stack", _step_apply_stack),
    ("app_bootstrap", _step_app_bootstrap),
    ("send_onboarding_link", _step_onboarding_link),
]


def run_provision(db: Session, tenant: Tenant, actor: str, ctx: dict | None = None) -> ProvisionJob:
    """Run the full pipeline. Safe to re-run after a failure — completed work
    is detected and skipped."""
    ctx = ctx or {}
    job = ProvisionJob(tenant_id=tenant.id)
    db.add(job)
    db.flush()
    tenant.status = TenantStatus.PROVISIONING
    audit.record(db, actor, "tenant.provision.started", tenant.id, job_id=job.id)

    for position, (name, fn) in enumerate(PIPELINE):
        step = ProvisionStep(job_id=job.id, position=position, name=name)
        db.add(step)
        try:
            step.status, step.detail = fn(db, tenant, ctx)
        except Exception as exc:  # noqa: BLE001 — any step failure fails the job
            logger.exception("provision step %s failed for %s", name, tenant.slug)
            step.status = "failed"
            step.detail = str(exc)[:2000]
            job.status = "failed"
            job.error = f"{name}: {exc}"[:2000]
            job.finished_at = utcnow()
            tenant.status = TenantStatus.FAILED
            audit.record(db, actor, "tenant.provision.failed", tenant.id, job_id=job.id, step=name)
            db.commit()
            return job
        db.flush()

    if ctx.get("record_link"):
        job.onboarding_link = ctx.get("onboarding_link")
    job.status = "succeeded"
    job.finished_at = utcnow()
    tenant.status = TenantStatus.ACTIVE
    audit.record(db, actor, "tenant.provision.succeeded", tenant.id, job_id=job.id)
    db.commit()
    return job


def take_offline(db: Session, tenant: Tenant, actor: str) -> None:
    """Take a town offline WITHOUT deleting anything. Stops the running stack so
    it consumes no compute and is no longer reachable, but keeps every DB /
    Redis / uploads volume, the KMS key, and all brokered secrets intact.
    Fully reversible via bring_online. This is NOT decommissioning — no
    crypto-shred, no data loss."""
    if settings.apply_stacks:
        stack.stop_stack(tenant)
    tenant.status = TenantStatus.OFFLINE
    audit.record(db, actor, "tenant.taken_offline", tenant.id, data_retained=True)
    db.commit()


def bring_online(db: Session, tenant: Tenant, actor: str) -> None:
    """Bring a previously offline town back up with all its data intact."""
    if settings.apply_stacks:
        stack.start_stack(tenant)
    tenant.status = TenantStatus.ACTIVE
    audit.record(db, actor, "tenant.brought_online", tenant.id)
    db.commit()


def decommission(db: Session, tenant: Tenant, actor: str) -> None:
    """Offboard with crypto-shred (plan A7): destroy the town's KMS wrapping
    key so every envelope-encrypted PII field becomes unrecoverable, then
    remove brokered secrets and the rendered stack."""
    if settings.apply_stacks:
        stack.down_stack(tenant, remove_volumes=True)
    stack.remove_rendered_stack(tenant)

    shredded_key = tenant.kms_key_ref
    tenant.kms_key_ref = None  # real KMS driver issues DestroyCryptoKeyVersion here

    for secret in list(tenant.secrets):
        db.delete(secret)

    tenant.status = TenantStatus.DECOMMISSIONED
    tenant.running_version = None
    tenant.target_version = None
    audit.record(
        db,
        actor,
        "tenant.decommissioned",
        tenant.id,
        kms_key_destroyed=shredded_key,
        crypto_shred=True,
    )
    db.commit()
