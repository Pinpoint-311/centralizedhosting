"""Operator SSO (OIDC) + federation configuration.

Sign-in flow: /login redirects to the host's IdP; /callback validates the ID
token, maps groups→role, and mints an HttpOnly session cookie. Federation is
configured at runtime (issuer + client id/secret) and the secret is stored
encrypted via the panel's secret manager.
"""

import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from orchestrator import audit, oidc
from orchestrator.config import settings
from orchestrator.db import get_db
from orchestrator.models import FederationConfig
from orchestrator.security import (
    ROLES,
    encrypt_value,
    mint_session,
    require_admin,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# In-memory login-state store (single-process panel). state -> context + expiry.
_pending: dict[str, dict] = {}
_STATE_TTL = 600  # seconds


def _sweep() -> None:
    now = time.time()
    for s in [s for s, v in _pending.items() if v["exp"] < now]:
        _pending.pop(s, None)


def _redirect_uri(request: Request) -> str:
    base = settings.panel_public_url.rstrip("/") if settings.panel_public_url else str(request.base_url).rstrip("/")
    return f"{base}/api/auth/sso/callback"


def _frontend_base(request: Request) -> str:
    return settings.panel_public_url.rstrip("/") if settings.panel_public_url else str(request.base_url).rstrip("/")


# ------------------------------------------------------------------ sign-in

@router.get("/sso/status")
def sso_status(db: Session = Depends(get_db)):
    """PUBLIC — whether SSO is configured, so the login screen can show the
    'Sign in with SSO' button. No secrets."""
    cfg = oidc.get_config(db)
    return {
        "configured": oidc.is_configured(db),
        "provider": (cfg.provider if cfg else "oidc"),
        "login_path": "/api/auth/sso/login",
    }


@router.get("/sso/login")
def sso_login(request: Request, db: Session = Depends(get_db)):
    cfg = oidc.get_config(db)
    if not oidc.is_configured(db):
        raise HTTPException(503, "SSO is not configured")
    try:
        meta = oidc.discover(cfg.issuer)
    except Exception as exc:
        raise HTTPException(502, f"Could not reach the identity provider: {exc}")
    import secrets as pysecrets

    state = pysecrets.token_urlsafe(24)
    nonce = pysecrets.token_urlsafe(24)
    verifier, challenge = oidc.make_pkce()
    _sweep()
    _pending[state] = {"nonce": nonce, "verifier": verifier, "exp": time.time() + _STATE_TTL}
    url = oidc.authorize_url(cfg, meta, _redirect_uri(request), state, nonce, challenge)
    return RedirectResponse(url, status_code=302)


@router.get("/sso/callback")
def sso_callback(request: Request, db: Session = Depends(get_db),
                 code: str = "", state: str = "", error: str = ""):
    front = _frontend_base(request)
    if error:
        return RedirectResponse(f"{front}/?sso_error={error}", status_code=302)
    ctx = _pending.pop(state, None)
    if not ctx or ctx["exp"] < time.time():
        return RedirectResponse(f"{front}/?sso_error=expired_state", status_code=302)
    cfg = oidc.get_config(db)
    if not oidc.is_configured(db):
        return RedirectResponse(f"{front}/?sso_error=not_configured", status_code=302)
    try:
        meta = oidc.discover(cfg.issuer)
        tokens = oidc.exchange_code(cfg, meta, code, _redirect_uri(request), ctx["verifier"])
        id_token = tokens.get("id_token")
        if not id_token:
            raise ValueError("no id_token in token response")
        claims = oidc.verify_id_token(cfg, meta, id_token, ctx["nonce"])
    except Exception as exc:
        return RedirectResponse(f"{front}/?sso_error=verification_failed", status_code=302)

    actor = oidc.operator_identity(claims)
    role = oidc.role_from_claims(cfg, claims)
    audit.record(db, actor, "auth.sso_login", None, role=role, provider=cfg.provider)
    db.commit()

    session = mint_session(actor, role)
    resp = RedirectResponse(f"{front}/", status_code=302)
    resp.set_cookie(
        settings.session_cookie_name, session,
        max_age=settings.session_ttl_minutes * 60,
        httponly=True, secure=not settings.panel_cookie_insecure,
        samesite="lax", path="/",
    )
    return resp


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(settings.session_cookie_name, path="/")
    return {"ok": True}


# ------------------------------------------------------------ federation config

class FederationUpdate(BaseModel):
    enabled: bool = False
    provider: str = Field(default="oidc", max_length=40)
    issuer: str | None = None
    client_id: str | None = None
    client_secret: str | None = None  # write-only; omit/blank to keep existing
    groups_claim: str = "groups"
    group_role_map: dict[str, str] = {}
    default_role: str = "viewer"


def _config_out(cfg: FederationConfig | None) -> dict:
    if not cfg:
        return {"enabled": False, "provider": "oidc", "issuer": None, "client_id": None,
                "client_secret_set": False, "groups_claim": "groups", "group_role_map": {},
                "default_role": "viewer"}
    return {
        "enabled": cfg.enabled,
        "provider": cfg.provider,
        "issuer": cfg.issuer,
        "client_id": cfg.client_id,
        "client_secret_set": bool(cfg.client_secret_encrypted),  # never return the secret
        "groups_claim": cfg.groups_claim,
        "group_role_map": cfg.group_role_map or {},
        "default_role": cfg.default_role,
    }


@router.get("/federation")
def get_federation(db: Session = Depends(get_db), _: str = Depends(require_admin)):
    return _config_out(oidc.get_config(db))


@router.put("/federation")
def put_federation(body: FederationUpdate, db: Session = Depends(get_db),
                   actor: str = Depends(require_admin)):
    if body.default_role not in ROLES:
        raise HTTPException(422, f"default_role must be one of {ROLES}")
    for role in body.group_role_map.values():
        if role not in ROLES:
            raise HTTPException(422, f"group_role_map roles must be one of {ROLES}")

    cfg = oidc.get_config(db)
    if not cfg:
        cfg = FederationConfig(id="default")
        db.add(cfg)
    cfg.enabled = body.enabled
    cfg.provider = body.provider
    cfg.issuer = (body.issuer or "").rstrip("/") or None
    cfg.client_id = body.client_id or None
    if body.client_secret:  # only replace when a new value is supplied
        cfg.client_secret_encrypted = encrypt_value(body.client_secret)
    cfg.groups_claim = body.groups_claim or "groups"
    cfg.group_role_map = body.group_role_map
    cfg.default_role = body.default_role
    cfg.updated_by = actor

    if cfg.enabled and not (cfg.issuer and cfg.client_id and cfg.client_secret_encrypted):
        raise HTTPException(422, "issuer, client_id, and client_secret are required to enable SSO")

    oidc._DISCO_CACHE.clear()
    audit.record(db, actor, "auth.federation_updated", None,
                 enabled=cfg.enabled, provider=cfg.provider, issuer=cfg.issuer)
    db.commit()
    return _config_out(cfg)


@router.post("/federation/test")
def test_federation(db: Session = Depends(get_db), _: str = Depends(require_admin)):
    """Live discovery check against the configured issuer."""
    cfg = oidc.get_config(db)
    if not cfg or not cfg.issuer:
        raise HTTPException(400, "Set an issuer first")
    try:
        meta = oidc.discover(cfg.issuer, force=True)
    except Exception as exc:
        raise HTTPException(502, f"Discovery failed: {exc}")
    return {"ok": True, "authorization_endpoint": meta.get("authorization_endpoint"),
            "issuer": meta.get("issuer")}
