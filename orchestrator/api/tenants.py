"""B1 tenant registry + B2 provisioning + lifecycle (suspend/resume/decommission)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator import audit, managed_settings, provisioner
from orchestrator.app_client import client_for_tenant
from orchestrator.config import settings
from orchestrator.db import get_db
from orchestrator.key_catalog import normalize_assignments
from orchestrator.models import ProvisionJob, Tenant, TenantStatus
from orchestrator.schemas import (
    BulkResultRow,
    BulkTenantCreate,
    ProvisionJobOut,
    TenantCreate,
    TenantOut,
    TenantUpdate,
)
from orchestrator.security import require_approver, require_operator, require_panel_token

router = APIRouter(prefix="/api/tenants", tags=["tenants"])


def _get_tenant(db: Session, tenant_id: str) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    return tenant


@router.post("", response_model=TenantOut, status_code=201)
def create_tenant(
    body: TenantCreate,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    if db.execute(select(Tenant).where(Tenant.slug == body.slug)).scalar_one_or_none():
        raise HTTPException(409, f"Tenant slug '{body.slug}' already exists")
    data = body.model_dump()
    data["key_assignments"] = normalize_assignments(data.get("key_assignments"))
    data["managed_settings"] = managed_settings.defaults()
    tenant = Tenant(subdomain=body.slug, **data)
    db.add(tenant)
    audit.record(db, actor, "tenant.created", tenant.id, slug=tenant.slug, name=tenant.name)
    db.commit()
    return tenant


@router.patch("/{tenant_id}", response_model=TenantOut)
def update_tenant(
    tenant_id: str,
    body: TenantUpdate,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    """Edit contact info and domain after creation. Slug/subdomain are
    immutable (DNS + provisioned resources depend on them)."""
    tenant = _get_tenant(db, tenant_id)
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(tenant, field, value)
    audit.record(db, actor, "tenant.updated", tenant.id, fields=sorted(changes.keys()))
    db.commit()
    return tenant


@router.post("/bulk", response_model=list[BulkResultRow], status_code=201)
def bulk_create(
    body: BulkTenantCreate,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    """Onboard many municipalities at once (e.g. from a CSV import). Each row is
    independent — a bad row fails only itself and reports why."""
    results: list[BulkResultRow] = []
    for row in body.tenants:
        existing = db.execute(select(Tenant).where(Tenant.slug == row.slug)).scalar_one_or_none()
        if existing:
            results.append(BulkResultRow(slug=row.slug, ok=False, error="slug already exists"))
            continue
        try:
            data = row.model_dump()
            data["key_assignments"] = normalize_assignments(data.get("key_assignments"))
            tenant = Tenant(subdomain=row.slug, **data)
            db.add(tenant)
            db.flush()
            audit.record(db, actor, "tenant.created", tenant.id, slug=tenant.slug, via="bulk")
            results.append(BulkResultRow(slug=row.slug, ok=True, id=tenant.id))
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            results.append(BulkResultRow(slug=row.slug, ok=False, error=str(exc)[:200]))
    db.commit()
    return results


@router.get("", response_model=list[TenantOut])
def list_tenants(
    status: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: str = Depends(require_panel_token),
):
    query = select(Tenant).order_by(Tenant.created_at)
    if status:
        query = query.where(Tenant.status == status)
    rows = db.execute(query).scalars().all()
    if tag:
        rows = [t for t in rows if tag in (t.tags or [])]
    return rows


@router.get("/{tenant_id}", response_model=TenantOut)
def get_tenant(
    tenant_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_panel_token),
):
    return _get_tenant(db, tenant_id)


@router.post("/{tenant_id}/provision", response_model=ProvisionJobOut)
def provision_tenant(
    tenant_id: str,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    tenant = _get_tenant(db, tenant_id)
    if tenant.status == TenantStatus.DECOMMISSIONED:
        raise HTTPException(409, "Tenant is decommissioned")
    return provisioner.run_provision(db, tenant, actor)


@router.get("/{tenant_id}/transparency")
def transparency(
    tenant_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_panel_token),
):
    """The town's trust report: exactly what metadata the panel holds about
    this town, an explicit statement of what it does NOT hold (resident data),
    and every state action against it. The panel is fully air-gapped from
    resident data — there is no break-glass, no path into the town's instance."""
    from orchestrator.models import AuditLog

    tenant = _get_tenant(db, tenant_id)
    access_events = db.execute(
        select(AuditLog).where(
            AuditLog.tenant_id == tenant_id,
            AuditLog.action.in_(["tenant.legal_hold_set"]),
        ).order_by(AuditLog.seq.desc()).limit(50)
    ).scalars().all()
    return {
        "town": {"name": tenant.name, "slug": tenant.slug, "host": tenant.external_host},
        "metadata_panel_holds": [
            "Town name, slug, region, plan, status",
            "Contact info you provided",
            "Provisioned resource references (DB name, bucket, KMS key ref — not contents)",
            "Running/target version + reachability (uptime)",
            "Aggregate API-usage counters for billing",
            "State-set policy (retention, legal hold, security posture)",
        ],
        "panel_never_holds": [
            "Resident names, contacts, or any personally identifiable information",
            "Service-request contents or attachments",
            "Your residents' data in any form — it stays in your isolated instance",
            "Your town's individual 311 figures shown to other towns (region-only)",
            "Any login or path into your instance — there is no break-glass access",
        ],
        "state_access_events": [
            {"action": e.action, "actor": e.actor, "at": e.created_at.isoformat(),
             "detail": {k: v for k, v in (e.detail or {}).items() if k != "reason"} | (
                 {"reason": e.detail.get("reason")} if e.detail and e.detail.get("reason") else {})}
            for e in access_events
        ],
    }


@router.get("/{tenant_id}/stack-preview")
def stack_preview(
    tenant_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_panel_token),
):
    """Preview the exact compose + env that provisioning would render for this
    town (secret values masked). Lets an operator review before deploying."""
    from orchestrator import stack

    tenant = _get_tenant(db, tenant_id)
    version = tenant.target_version or provisioner._target_version(db, tenant)
    rel = provisioner.release_for_version(db, version)
    preview = stack.preview_stack(
        tenant,
        provisioner._secrets_bundle(db, tenant),
        version,
        backend_digest=rel.backend_digest if rel else None,
        frontend_digest=rel.frontend_digest if rel else None,
    )
    return {"version": version, **preview}


@router.get("/{tenant_id}/jobs", response_model=list[ProvisionJobOut])
def list_jobs(
    tenant_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_panel_token),
):
    _get_tenant(db, tenant_id)
    return (
        db.execute(
            select(ProvisionJob)
            .where(ProvisionJob.tenant_id == tenant_id)
            .order_by(ProvisionJob.created_at.desc())
        )
        .scalars()
        .all()
    )


def _set_lifecycle(db: Session, tenant: Tenant, state: str, actor: str) -> Tenant:
    if settings.apply_stacks:
        client = client_for_tenant(
            tenant,
            provisioning_token=provisioner.get_platform_secret(db, tenant.id, "PROVISIONING_TOKEN"),
        )
        try:
            client.set_lifecycle(state)
        finally:
            client.close()
    tenant.status = TenantStatus.SUSPENDED if state == "suspended" else TenantStatus.ACTIVE
    audit.record(db, actor, f"tenant.{state}", tenant.id)
    db.commit()
    return tenant


@router.post("/{tenant_id}/suspend", response_model=TenantOut)
def suspend_tenant(
    tenant_id: str,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    tenant = _get_tenant(db, tenant_id)
    if tenant.status != TenantStatus.ACTIVE:
        raise HTTPException(409, f"Only active tenants can be suspended (is {tenant.status})")
    return _set_lifecycle(db, tenant, "suspended", actor)


@router.post("/{tenant_id}/resume", response_model=TenantOut)
def resume_tenant(
    tenant_id: str,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    tenant = _get_tenant(db, tenant_id)
    if tenant.status != TenantStatus.SUSPENDED:
        raise HTTPException(409, f"Only suspended tenants can be resumed (is {tenant.status})")
    return _set_lifecycle(db, tenant, "active", actor)


@router.post("/{tenant_id}/take-offline", response_model=TenantOut)
def take_tenant_offline(
    tenant_id: str,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    """Take the instance offline while retaining ALL data (DB, PII, uploads,
    KMS key, secrets). Reversible — not a decommission."""
    tenant = _get_tenant(db, tenant_id)
    if tenant.status not in (TenantStatus.ACTIVE, TenantStatus.SUSPENDED):
        raise HTTPException(409, f"Only active/suspended tenants can be taken offline (is {tenant.status})")
    provisioner.take_offline(db, tenant, actor)
    return tenant


@router.post("/{tenant_id}/bring-online", response_model=TenantOut)
def bring_tenant_online(
    tenant_id: str,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    """Bring an offline instance back up with all data intact."""
    tenant = _get_tenant(db, tenant_id)
    if tenant.status != TenantStatus.OFFLINE:
        raise HTTPException(409, f"Only offline tenants can be brought online (is {tenant.status})")
    provisioner.bring_online(db, tenant, actor)
    return tenant


@router.post("/{tenant_id}/decommission", response_model=TenantOut)
def decommission_tenant(
    tenant_id: str,
    confirm_slug: str = Query(description="Must equal the tenant slug — crypto-shred is irreversible"),
    db: Session = Depends(get_db),
    actor: str = Depends(require_approver),
):
    tenant = _get_tenant(db, tenant_id)
    if confirm_slug != tenant.slug:
        raise HTTPException(400, "confirm_slug does not match — decommission aborted")
    if tenant.status == TenantStatus.DECOMMISSIONED:
        raise HTTPException(409, "Tenant already decommissioned")
    provisioner.decommission(db, tenant, actor)
    return tenant
