"""B6/A8 — break-glass: panel-issued, time-boxed, audited state-ops access.

The minted token is distinct from town staff login; the app (in managed mode)
verifies it against the shared panel key and logs the session in the town's
own audit trail as actor_type="state_ops". The panel stores only the grant
metadata — the token itself is returned exactly once.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator import audit
from orchestrator.db import get_db
from orchestrator.models import BreakGlassGrant, Tenant, utcnow
from orchestrator.schemas import BreakGlassIssued, BreakGlassOut, BreakGlassRequest
from orchestrator.security import (
    clamp_break_glass_expiry,
    mint_break_glass_token,
    require_panel_token,
)

router = APIRouter(prefix="/api/breakglass", tags=["break-glass"])


@router.post("", response_model=BreakGlassIssued, status_code=201)
def issue_grant(
    body: BreakGlassRequest,
    db: Session = Depends(get_db),
    operator: str = Depends(require_panel_token),
):
    tenant = db.get(Tenant, body.tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    grant = BreakGlassGrant(
        tenant_id=tenant.id,
        actor=body.actor,
        reason=body.reason,
        expires_at=clamp_break_glass_expiry(body.minutes),
    )
    db.add(grant)
    db.flush()
    token = mint_break_glass_token(tenant.id, body.actor, grant.token_id, grant.expires_at)
    audit.record(
        db, operator, "breakglass.issued", tenant.id,
        grant_id=grant.id, grantee=body.actor, reason=body.reason,
        expires_at=grant.expires_at.isoformat(),
    )
    db.commit()
    return BreakGlassIssued(
        id=grant.id,
        tenant_id=grant.tenant_id,
        actor=grant.actor,
        reason=grant.reason,
        expires_at=grant.expires_at,
        revoked_at=grant.revoked_at,
        created_at=grant.created_at,
        token=token,
    )


@router.get("", response_model=list[BreakGlassOut])
def list_grants(
    db: Session = Depends(get_db),
    _: str = Depends(require_panel_token),
):
    return db.execute(
        select(BreakGlassGrant).order_by(BreakGlassGrant.created_at.desc())
    ).scalars().all()


@router.post("/{grant_id}/revoke", response_model=BreakGlassOut)
def revoke_grant(
    grant_id: str,
    db: Session = Depends(get_db),
    operator: str = Depends(require_panel_token),
):
    grant = db.get(BreakGlassGrant, grant_id)
    if not grant:
        raise HTTPException(404, "Grant not found")
    if grant.revoked_at:
        raise HTTPException(409, "Grant already revoked")
    grant.revoked_at = utcnow()
    audit.record(db, operator, "breakglass.revoked", grant.tenant_id, grant_id=grant.id)
    db.commit()
    return grant
