"""Self-service municipality hosting requests: public intake (opt-in) + an
operator approval inbox."""

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator import audit
from orchestrator.config import settings
from orchestrator.db import get_db
from orchestrator.models import Tenant, TownRequest, utcnow
from orchestrator.schemas import TenantOut, TownRequestCreate, TownRequestOut
from orchestrator.security import require_operator, require_panel_token

router = APIRouter(prefix="/api/requests", tags=["requests"])

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:63]


@router.post("", response_model=TownRequestOut, status_code=201)
def submit_request(body: TownRequestCreate, db: Session = Depends(get_db)):
    """PUBLIC (no auth) — a municipality asks to be hosted. Opt-in via
    PUBLIC_REQUESTS_ENABLED; put rate-limiting/CAPTCHA in front in production."""
    if not settings.public_requests_enabled:
        raise HTTPException(404, "Public request intake is not enabled")
    req = TownRequest(
        name=body.name,
        requested_slug=(_slugify(body.requested_slug) if body.requested_slug else None),
        contact_name=body.contact_name,
        contact_email=body.contact_email,
        message=body.message,
    )
    db.add(req)
    db.commit()
    return req


@router.get("", response_model=list[TownRequestOut])
def list_requests(
    status: str | None = None,
    db: Session = Depends(get_db),
    _: str = Depends(require_panel_token),
):
    q = select(TownRequest).order_by(TownRequest.created_at.desc())
    if status:
        q = q.where(TownRequest.status == status)
    return db.execute(q).scalars().all()


@router.post("/{request_id}/approve", response_model=TenantOut)
def approve_request(
    request_id: str,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    """Approve a pending request → create the municipality (pending provisioning)."""
    req = db.get(TownRequest, request_id)
    if not req:
        raise HTTPException(404, "Request not found")
    if req.status != "pending":
        raise HTTPException(409, f"Request already {req.status}")

    slug = req.requested_slug or _slugify(req.name)
    if not _SLUG_RE.match(slug):
        raise HTTPException(422, "Could not derive a valid slug; edit the request first")
    if db.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none():
        raise HTTPException(409, f"Slug '{slug}' already exists")

    tenant = Tenant(
        name=req.name,
        slug=slug,
        subdomain=slug,
        contact_name=req.contact_name,
        contact_email=req.contact_email,
    )
    db.add(tenant)
    db.flush()
    req.status = "approved"
    req.tenant_id = tenant.id
    req.decided_at = utcnow()
    req.decided_by = actor
    audit.record(db, actor, "request.approved", tenant.id, request_id=req.id, slug=slug)
    db.commit()
    return tenant


@router.post("/{request_id}/reject", response_model=TownRequestOut)
def reject_request(
    request_id: str,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    req = db.get(TownRequest, request_id)
    if not req:
        raise HTTPException(404, "Request not found")
    if req.status != "pending":
        raise HTTPException(409, f"Request already {req.status}")
    req.status = "rejected"
    req.decided_at = utcnow()
    req.decided_by = actor
    audit.record(db, actor, "request.rejected", None, request_id=req.id)
    db.commit()
    return req
