"""Cloud service-provider configuration — the capabilities a state hosts for
its towns (AI, translation, identity) plus one-click cloud profiles. Ported from
the Pinpoint 311 app's /api/system provider endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from orchestrator import audit, providers
from orchestrator.db import get_db
from orchestrator.security import require_admin, require_operator

router = APIRouter(prefix="/api/providers", tags=["providers"])

CAPABILITIES = ("ai", "translation", "identity")


def _cap(capability: str) -> str:
    if capability not in CAPABILITIES:
        raise HTTPException(404, f"Unknown capability '{capability}'")
    return capability


@router.get("/{capability}/catalog")
def catalog(capability: str, db: Session = Depends(get_db), _: str = Depends(require_operator)):
    return providers.catalog_for_api(db, _cap(capability))


class SaveProvider(BaseModel):
    provider: str
    model: str | None = None
    credentials: dict[str, str] = {}


@router.post("/{capability}/save")
def save(capability: str, body: SaveProvider, db: Session = Depends(get_db),
         actor: str = Depends(require_admin)):
    try:
        providers.save_provider(db, _cap(capability), body.provider, body.model, body.credentials)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    audit.record(db, actor, "provider.saved", capability, provider=body.provider)
    db.commit()
    return providers.catalog_for_api(db, capability)


@router.post("/{capability}/test")
def test(capability: str, db: Session = Depends(get_db), _: str = Depends(require_operator)):
    return providers.provider_status(db, _cap(capability))


@router.get("/cloud-profile")
def cloud_profile(db: Session = Depends(get_db), _: str = Depends(require_operator)):
    return providers.cloud_profile_state(db)


class ApplyProfile(BaseModel):
    profile: str
    apply_identity: bool = False


@router.post("/cloud-profile")
def set_cloud_profile(body: ApplyProfile, db: Session = Depends(get_db),
                      actor: str = Depends(require_admin)):
    try:
        state = providers.apply_cloud_profile(db, body.profile, body.apply_identity)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    audit.record(db, actor, "provider.cloud_profile_applied", body.profile)
    db.commit()
    return state
