"""Upstream app updates: check, review, approve.

The shape is deliberate. Checking is safe and can run unattended; approving is
the only thing that creates a Release, and it is an operator action that lands in
the audit chain. Approval still does not deploy — it makes the build *eligible*
for the existing canary rollout, which an operator then starts and promotes.

So a build passes three human decisions before it reaches every town: approve
the candidate, start the rollout, promote past the canary.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator import audit, upstream
from orchestrator.config import settings
from orchestrator.db import get_db
from orchestrator.models import (
    Release,
    Tenant,
    TenantStatus,
    UpstreamCandidate,
    UpstreamStatus,
    utcnow,
)
from orchestrator.security import require_operator, require_panel_token

router = APIRouter(prefix="/api/upstream", tags=["upstream"])


class CandidateOut(BaseModel):
    id: str
    version: str
    channel: str
    git_sha: str | None = None
    backend_image: str
    frontend_image: str
    backend_digest: str
    frontend_digest: str
    db_revision: str | None = None
    min_db_revision: str | None = None
    stamp_complete: bool
    signature_verified: bool
    signature_detail: str | None = None
    status: str
    discovered_at: str
    reviewed_at: str | None = None
    reviewed_by: str | None = None
    review_note: str | None = None
    release_id: str | None = None
    compare_url: str | None = None
    schema_change: bool = False
    blockers: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ReviewBody(BaseModel):
    note: str | None = None
    # Required only when the build predates label stamping, so the operator has
    # to state the compatibility window rather than the panel inventing one.
    db_revision: str | None = None
    min_db_revision: str | None = None


def _fleet_revision(db: Session) -> str | None:
    """The db_revision the fleet's current release declares, for the delta."""
    current = db.execute(
        select(Release).order_by(Release.published_at.desc())
    ).scalars().first()
    return current.db_revision if current else None


def _fleet_sha(db: Session) -> str | None:
    """Commit the fleet last accepted, so the reviewer gets a compare range
    rather than a single commit link. Release rows carry no git sha, so this
    comes from the most recently approved candidate."""
    approved = db.execute(
        select(UpstreamCandidate)
        .where(UpstreamCandidate.status == UpstreamStatus.APPROVED)
        .order_by(UpstreamCandidate.reviewed_at.desc())
    ).scalars().first()
    return approved.git_sha if approved else None


def _blockers(db: Session, candidate: UpstreamCandidate) -> list[str]:
    """Everything that would stop this candidate from being deployable.

    Shown before approval so the reviewer sees the same facts the backend will
    enforce, rather than discovering them at the click.
    """
    out: list[str] = []
    if settings.cosign_verify and not candidate.signature_verified:
        out.append(f"Image signature not verified — {candidate.signature_detail}")
    if settings.require_signed_images and not (
        candidate.backend_digest and candidate.frontend_digest
    ):
        out.append("Images are not digest-pinned and REQUIRE_SIGNED_IMAGES is on")
    if not candidate.stamp_complete:
        out.append(
            "Build carries no migration stamp — supply db_revision and "
            "min_db_revision when approving"
        )
    if db.execute(
        select(Release).where(Release.version == candidate.version)
    ).scalar_one_or_none():
        out.append(f"Release {candidate.version} already exists")
    return out


def _out(db: Session, c: UpstreamCandidate) -> CandidateOut:
    model = CandidateOut.model_validate(
        {
            **{k: v for k, v in c.__dict__.items() if not k.startswith("_")},
            "discovered_at": c.discovered_at.isoformat(),
            "reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None,
        }
    )
    model.compare_url = upstream.compare_url(c, _fleet_sha(db))
    model.schema_change = bool(c.db_revision and c.db_revision != _fleet_revision(db))
    model.blockers = _blockers(db, c)
    return model


@router.get("/status")
def upstream_status(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    """What the fleet runs, what is waiting for review, and how checking is set up."""
    pending = db.execute(
        select(UpstreamCandidate)
        .where(UpstreamCandidate.status == UpstreamStatus.AVAILABLE)
        .order_by(UpstreamCandidate.discovered_at.desc())
    ).scalars().first()

    latest_release = db.execute(
        select(Release).order_by(Release.published_at.desc())
    ).scalars().first()

    versions = db.execute(
        select(Tenant.running_version).where(Tenant.status == TenantStatus.ACTIVE)
    ).scalars().all()
    running = sorted({v for v in versions if v})

    return {
        "enabled": settings.upstream_check_enabled,
        "channel": settings.upstream_channel,
        "poll_seconds": settings.upstream_check_seconds,
        "backend_image": settings.backend_image,
        "frontend_image": settings.frontend_image,
        "signature_enforced": settings.cosign_verify,
        "migrations_enabled": settings.migrate_on_upgrade,
        "backup_before_migrate": settings.backup_before_migrate and settings.backups_enabled,
        "latest_release": latest_release.version if latest_release else None,
        "fleet_versions": running,
        "fleet_drift": len(running) > 1,
        "pending": _out(db, pending) if pending else None,
    }


@router.post("/check")
def check_upstream(
    response: Response,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    """Look at the channel now. Read-only against the registry; files a
    candidate when the tag has moved. Never deploys."""
    if not settings.upstream_check_enabled:
        raise HTTPException(409, "Upstream checking is disabled (UPSTREAM_CHECK_ENABLED=false)")
    try:
        result = upstream.check(db, actor)
    except upstream.UpstreamError as exc:
        # A registry that is down is an operational fact, not a panel bug.
        raise HTTPException(502, str(exc)) from exc
    response.status_code = 200
    candidate = db.get(UpstreamCandidate, result["candidate_id"])
    return {"new": result["new"], "candidate": _out(db, candidate)}


@router.get("/candidates", response_model=list[CandidateOut])
def list_candidates(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    rows = db.execute(
        select(UpstreamCandidate).order_by(UpstreamCandidate.discovered_at.desc())
    ).scalars().all()
    return [_out(db, c) for c in rows]


def _candidate(db: Session, candidate_id: str) -> UpstreamCandidate:
    obj = db.get(UpstreamCandidate, candidate_id)
    if not obj:
        raise HTTPException(404, "Candidate not found")
    return obj


@router.post("/candidates/{candidate_id}/approve", response_model=CandidateOut)
def approve_candidate(
    candidate_id: str,
    body: ReviewBody,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    """Accept a candidate and publish it as a Release.

    Signatures are re-verified here rather than trusting the verdict recorded at
    discovery — a candidate can sit in the queue for days, and the check that
    matters is the one taken when the artifact is accepted.
    """
    candidate = _candidate(db, candidate_id)
    if candidate.status != UpstreamStatus.AVAILABLE:
        raise HTTPException(409, f"Candidate is {candidate.status}, not awaiting review")

    ok, detail = upstream.verify_signatures(
        f"{candidate.backend_image}@{candidate.backend_digest}",
        f"{candidate.frontend_image}@{candidate.frontend_digest}",
    )
    candidate.signature_verified = ok
    candidate.signature_detail = detail
    if settings.cosign_verify and not ok:
        audit.record(db, actor, "upstream.approval_blocked", None,
                     version=candidate.version, reason="signature", detail=detail)
        db.commit()
        raise HTTPException(422, f"Image signature verification failed: {detail}")

    db_revision = body.db_revision or candidate.db_revision
    min_db_revision = body.min_db_revision or candidate.min_db_revision
    if not db_revision:
        raise HTTPException(
            422,
            "This build carries no db_revision label, so the panel cannot gate its "
            "migrations. Supply db_revision and min_db_revision explicitly to approve it.",
        )
    if db.execute(
        select(Release).where(Release.version == candidate.version)
    ).scalar_one_or_none():
        raise HTTPException(409, f"Release {candidate.version} already published")

    release = Release(
        version=candidate.version,
        backend_image=candidate.backend_image,
        frontend_image=candidate.frontend_image,
        backend_digest=candidate.backend_digest,
        frontend_digest=candidate.frontend_digest,
        db_revision=db_revision,
        min_db_revision=min_db_revision,
        notes=(body.note or f"Approved from upstream {candidate.channel} by {actor}"),
    )
    db.add(release)
    db.flush()

    candidate.status = UpstreamStatus.APPROVED
    candidate.reviewed_at = utcnow()
    candidate.reviewed_by = actor
    candidate.review_note = body.note
    candidate.release_id = release.id
    candidate.db_revision = db_revision
    candidate.min_db_revision = min_db_revision

    audit.record(db, actor, "upstream.approved", None,
                 version=candidate.version, release_id=release.id,
                 backend_digest=candidate.backend_digest,
                 db_revision=db_revision, signature_verified=ok)
    audit.record(db, actor, "release.published", None,
                 version=release.version, db_revision=release.db_revision,
                 source="upstream")
    db.commit()
    return _out(db, candidate)


@router.post("/candidates/{candidate_id}/reject", response_model=CandidateOut)
def reject_candidate(
    candidate_id: str,
    body: ReviewBody,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    """Decline a build. The digest is remembered, so a later check does not
    re-offer what an operator already turned down."""
    candidate = _candidate(db, candidate_id)
    if candidate.status not in (UpstreamStatus.AVAILABLE, UpstreamStatus.SUPERSEDED):
        raise HTTPException(409, f"Candidate is {candidate.status} and cannot be rejected")
    candidate.status = UpstreamStatus.REJECTED
    candidate.reviewed_at = utcnow()
    candidate.reviewed_by = actor
    candidate.review_note = body.note
    audit.record(db, actor, "upstream.rejected", None,
                 version=candidate.version, note=body.note)
    db.commit()
    return _out(db, candidate)
