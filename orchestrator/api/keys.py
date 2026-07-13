"""Key-responsibility matrix — the catalog and per-tenant assignments behind
the panel's "who provides which API key" screen (extends B5)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from orchestrator import audit
from orchestrator.db import get_db
from orchestrator.key_catalog import (
    ASSIGNABLE_SERVICES,
    OWNERS,
    normalize_assignments,
)
from orchestrator.models import Tenant
from orchestrator.schemas import KeyAssignmentUpdate, KeyCatalogOut, TenantKeyAssignments
from orchestrator.secrets_policy import PLATFORM_MANAGED_KEYS, PLATFORM_MANAGED_PREFIXES
from orchestrator.security import require_panel_token

router = APIRouter(prefix="/api", tags=["key-responsibility"])


@router.get("/key-catalog", response_model=KeyCatalogOut)
def get_key_catalog(_: str = Depends(require_panel_token)):
    """The assignable services (state-or-town) plus the fixed infrastructure
    keys the state always owns (shown locked in the matrix)."""
    return KeyCatalogOut(
        assignable=ASSIGNABLE_SERVICES,
        infrastructure=sorted(PLATFORM_MANAGED_KEYS),
        infrastructure_prefixes=list(PLATFORM_MANAGED_PREFIXES),
        owners=list(OWNERS),
    )


def _tenant(db: Session, tenant_id: str) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    return tenant


@router.get("/tenants/{tenant_id}/key-assignments", response_model=TenantKeyAssignments)
def get_assignments(
    tenant_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_panel_token),
):
    tenant = _tenant(db, tenant_id)
    return TenantKeyAssignments(assignments=normalize_assignments(tenant.key_assignments))


@router.put("/tenants/{tenant_id}/key-assignments", response_model=TenantKeyAssignments)
def set_assignments(
    tenant_id: str,
    body: KeyAssignmentUpdate,
    db: Session = Depends(get_db),
    actor: str = Depends(require_panel_token),
):
    tenant = _tenant(db, tenant_id)
    merged = normalize_assignments({**normalize_assignments(tenant.key_assignments), **body.assignments})
    tenant.key_assignments = merged
    audit.record(db, actor, "tenant.key_assignments_updated", tenant.id, assignments=merged)
    db.commit()
    return TenantKeyAssignments(assignments=merged)
