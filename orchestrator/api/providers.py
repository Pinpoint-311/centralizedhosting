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
    settings: dict[str, str] = {}  # credential values, keyed by field


@router.post("/{capability}/save")
def save(capability: str, body: SaveProvider, db: Session = Depends(get_db),
         actor: str = Depends(require_admin)):
    try:
        providers.save_provider(db, _cap(capability), body.provider, body.model, body.settings)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    audit.record(db, actor, "provider.saved", capability, provider=body.provider)
    db.commit()
    return {"ok": True, "provider": body.provider}


@router.post("/{capability}/test")
def test(capability: str, db: Session = Depends(get_db), _: str = Depends(require_operator)):
    return providers.provider_status(db, _cap(capability))


class RefreshModels(BaseModel):
    provider: str


@router.post("/ai/models/refresh")
def refresh_ai_models(body: RefreshModels, db: Session = Depends(get_db),
                      _: str = Depends(require_operator)):
    """Model discovery. The control plane doesn't carry the cloud SDKs, so this
    returns the curated list rather than a live provider query — same response
    shape, with source='curated' so the UI labels it honestly."""
    meta = providers.AI_CATALOG.get(body.provider)
    if not meta:
        raise HTTPException(422, f"Unknown AI provider: {body.provider}")
    current_model = providers.get_setting(db, providers.MODEL_KEY)
    model_ids = {m["id"] for m in meta["models"]}
    return {
        "provider": body.provider,
        "models": meta["models"],
        "source": "curated",
        "fetched_at": None,
        "current_model": current_model,
        "current_model_available": (current_model in model_ids) if current_model else True,
    }


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
