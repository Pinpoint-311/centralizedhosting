"""B3 — release publishing + canary rollouts."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator import audit, rollout as rollout_engine
from orchestrator.config import settings
from orchestrator.db import get_db
from orchestrator.models import Release, Rollout, RolloutStatus
from orchestrator.schemas import ReleaseCreate, ReleaseOut, RolloutCreate, RolloutOut
from orchestrator.security import require_operator, require_panel_token

router = APIRouter(prefix="/api", tags=["releases"])


@router.post("/releases", response_model=ReleaseOut, status_code=201)
def publish_release(
    body: ReleaseCreate,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    if db.execute(select(Release).where(Release.version == body.version)).scalar_one_or_none():
        raise HTTPException(409, f"Release {body.version} already published")
    release = Release(
        version=body.version,
        backend_image=body.backend_image or settings.backend_image,
        frontend_image=body.frontend_image or settings.frontend_image,
        backend_digest=body.backend_digest,
        frontend_digest=body.frontend_digest,
        db_revision=body.db_revision,
        min_db_revision=body.min_db_revision,
        notes=body.notes,
    )
    db.add(release)
    audit.record(db, actor, "release.published", None,
                 version=release.version, db_revision=release.db_revision)
    db.commit()
    return release


@router.get("/releases", response_model=list[ReleaseOut])
def list_releases(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    return db.execute(select(Release).order_by(Release.published_at.desc())).scalars().all()


def _get_rollout(db: Session, rollout_id: str) -> Rollout:
    obj = db.get(Rollout, rollout_id)
    if not obj:
        raise HTTPException(404, "Rollout not found")
    return obj


@router.post("/rollouts", response_model=RolloutOut, status_code=201)
def start_rollout(
    body: RolloutCreate,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    release = db.get(Release, body.release_id)
    if not release:
        raise HTTPException(404, "Release not found")
    active = db.execute(
        select(Rollout).where(
            Rollout.status.in_(
                [RolloutStatus.PENDING, RolloutStatus.CANARY,
                 RolloutStatus.CANARY_PASSED, RolloutStatus.PROMOTING]
            )
        )
    ).scalar_one_or_none()
    if active:
        raise HTTPException(409, f"Rollout {active.id} is already in flight ({active.status})")
    try:
        obj = rollout_engine.create_rollout(db, release, body.canary_count)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return rollout_engine.execute_canary(db, obj, actor)


@router.post("/rollouts/{rollout_id}/promote", response_model=RolloutOut)
def promote_rollout(
    rollout_id: str,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    obj = _get_rollout(db, rollout_id)
    try:
        return rollout_engine.promote(db, obj, actor)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/rollouts/{rollout_id}/rollback", response_model=RolloutOut)
def rollback_rollout(
    rollout_id: str,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    obj = _get_rollout(db, rollout_id)
    if obj.status in (RolloutStatus.ROLLED_BACK,):
        raise HTTPException(409, "Rollout already rolled back")
    return rollout_engine.rollback(db, obj, actor)


@router.get("/rollouts", response_model=list[RolloutOut])
def list_rollouts(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    return db.execute(select(Rollout).order_by(Rollout.created_at.desc())).scalars().all()


@router.get("/rollouts/{rollout_id}", response_model=RolloutOut)
def get_rollout(
    rollout_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_panel_token),
):
    return _get_rollout(db, rollout_id)
