"""State-set managed policy (retention, legal hold, security, compliance) that
the panel pushes down to a town instance in managed mode."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator import audit, managed_settings
from orchestrator.app_client import client_for_tenant
from orchestrator.config import settings
from orchestrator.db import get_db
from orchestrator.models import TelemetrySnapshot, Tenant
from orchestrator.provisioner import get_platform_secret
from orchestrator.schemas import ManagedSettingsUpdate
from orchestrator.security import require_approver, require_operator, require_panel_token

router = APIRouter(prefix="/api", tags=["managed-settings"])


@router.get("/managed-settings/catalog")
def catalog(_: str = Depends(require_panel_token)):
    """Field definitions for the managed-policy editor."""
    return {"catalog": managed_settings.catalog()}


def _tenant(db: Session, tenant_id: str) -> Tenant:
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(404, "Tenant not found")
    return t


@router.get("/tenants/{tenant_id}/managed-settings")
def get_settings(tenant_id: str, db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    t = _tenant(db, tenant_id)
    return {"settings": managed_settings.normalize(t.managed_settings)}


@router.put("/tenants/{tenant_id}/managed-settings")
def put_settings(
    tenant_id: str,
    body: ManagedSettingsUpdate,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    t = _tenant(db, tenant_id)
    merged = managed_settings.normalize({**managed_settings.normalize(t.managed_settings), **body.settings})
    t.managed_settings = merged
    # Push to the running instance when applying; otherwise it lands at next provision.
    pushed = False
    if settings.apply_stacks:
        client = client_for_tenant(
            t, provisioning_token=get_platform_secret(db, t.id, "PROVISIONING_TOKEN")
        )
        try:
            client.set_managed_settings(merged)
            pushed = True
        except Exception:
            pushed = False
        finally:
            client.close()
    audit.record(db, actor, "tenant.managed_settings_updated", t.id, keys=sorted(body.settings.keys()))
    db.commit()
    return {"settings": merged, "pushed_to_instance": pushed}


# ---- Legal hold (shared: state OR town can place; effective = OR) ----------

def _town_legal_hold(db: Session, tenant_id: str) -> bool:
    snap = db.execute(
        select(TelemetrySnapshot)
        .where(TelemetrySnapshot.tenant_id == tenant_id)
        .order_by(TelemetrySnapshot.collected_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return bool(snap and snap.payload and snap.payload.get("legal_hold"))


class LegalHoldRequest(BaseModel):
    on: bool
    reason: str = Field(min_length=3, max_length=500)


@router.get("/tenants/{tenant_id}/legal-hold")
def get_legal_hold(tenant_id: str, db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    t = _tenant(db, tenant_id)
    state_hold = bool(managed_settings.normalize(t.managed_settings).get("legal_hold"))
    town_hold = _town_legal_hold(db, tenant_id)
    return {
        "state_hold": state_hold,
        "town_hold": town_hold,
        "effective": state_hold or town_hold,  # neither party can clear the other's
    }


@router.post("/tenants/{tenant_id}/legal-hold")
def set_legal_hold(
    tenant_id: str,
    body: LegalHoldRequest,
    db: Session = Depends(get_db),
    actor: str = Depends(require_approver),
):
    """Place or lift the STATE's legal hold. The town's own hold is independent;
    a request purge is blocked while EITHER hold is on."""
    t = _tenant(db, tenant_id)
    merged = managed_settings.normalize(t.managed_settings)
    merged["legal_hold"] = body.on
    t.managed_settings = merged
    pushed = False
    if settings.apply_stacks:
        client = client_for_tenant(
            t, provisioning_token=get_platform_secret(db, t.id, "PROVISIONING_TOKEN")
        )
        try:
            client.set_managed_settings(merged)
            pushed = True
        except Exception:
            pushed = False
        finally:
            client.close()
    audit.record(
        db, actor, "tenant.legal_hold_set", t.id,
        state_hold=body.on, reason=body.reason,
    )
    db.commit()
    town_hold = _town_legal_hold(db, tenant_id)
    return {"state_hold": body.on, "town_hold": town_hold, "effective": body.on or town_hold,
            "pushed_to_instance": pushed}
