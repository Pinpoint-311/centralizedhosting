"""B3 — release publishing + canary rollouts."""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator import audit, rollout as rollout_engine
from orchestrator.config import settings
from orchestrator.db import get_db
from orchestrator.models import Release, Rollout, RolloutStatus
from orchestrator.schemas import ReleaseCreate, ReleaseOut, RolloutCreate, RolloutOut
from orchestrator.security import require_operator, require_panel_token

router = APIRouter(prefix="/api", tags=["releases"])


def _run_in_background(key: str, engine_fn, rollout_id: str, actor: str) -> None:
    """Roll out on a background thread.

    Each phase deploys to every town in the wave and can run for minutes; inline
    it held the request open the whole time. Same lease as provisioning, so two
    workers can't drive the same rollout.
    """
    from orchestrator import jobs
    from orchestrator.db import SessionLocal
    from orchestrator.models import Rollout as _Rollout

    def _work():
        with SessionLocal() as session:
            engine_fn(session, session.get(_Rollout, rollout_id), actor)

    if not jobs.submit(key, _work):
        raise HTTPException(409, "This rollout is already being advanced")


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
    response: Response,
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
    db.commit()
    _run_in_background(f"rollout:{obj.id}", rollout_engine.execute_canary, obj.id, actor)
    response.status_code = 202
    db.refresh(obj)
    return obj


@router.post("/rollouts/{rollout_id}/promote", response_model=RolloutOut)
def promote_rollout(
    rollout_id: str,
    response: Response,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    obj = _get_rollout(db, rollout_id)
    if obj.status != RolloutStatus.CANARY_PASSED:
        raise HTTPException(409, f"Rollout is {obj.status}; only a passed canary can be promoted")
    _run_in_background(f"rollout:{obj.id}", rollout_engine.promote, obj.id, actor)
    response.status_code = 202
    db.refresh(obj)
    return obj


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
