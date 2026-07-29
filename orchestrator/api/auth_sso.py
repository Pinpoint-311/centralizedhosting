"""Operator SSO (OIDC) sign-in.

Sign-in flow: /sso/login redirects to the host's IdP; /sso/callback validates
the ID token, matches the operator to a User row by email, and mints the
app-style JWT bearer.

The identity provider is configured in ONE place — Setup → Integration →
Staff Sign-In, which writes the app's provider catalog (Auth0 / Entra / Okta /
generic OIDC). There is no separate federation editor: a second configurator
for the same thing meant two screens could disagree about who signs people in.
"""

import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orchestrator import audit, oidc
from orchestrator.config import settings
from orchestrator.db import get_db
from orchestrator.models import User, utcnow
from orchestrator.security import mint_session
from orchestrator.user_auth import create_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Why a sign-in was refused. The app distinguishes these, and so do we: an
# operator who exists but is disabled needs a different fix from one who was
# never added, and lumping them together sends everyone hunting the wrong thing.
SSO_DENY_REASONS = ("no_email", "not_provisioned", "account_disabled")

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

@router.get("/status")
def auth_status(db: Session = Depends(get_db)):
    """PUBLIC — authentication configuration status. The app's /auth/status,
    plus whether the first-run password path is still open."""
    cfg = oidc.effective_config(db)
    configured = cfg is not None
    return {
        # App-compatible fields.
        "auth0_configured": configured,
        "provider": (cfg.provider if cfg else None),
        "message": "Ready" if configured else "No identity provider configured",
        # Control-plane addition: the login screen offers the first-run
        # password form only while this is true (see users._bootstrap_gate_open).
        "bootstrap_available": not configured,
    }


@router.get("/sso/status")
def sso_status(db: Session = Depends(get_db)):
    """PUBLIC — whether SSO is configured, so the login screen can show the
    'Sign in with SSO' button. No secrets."""
    cfg = oidc.effective_config(db)
    return {
        "configured": cfg is not None,
        "provider": (cfg.provider if cfg else "oidc"),
        "login_path": "/api/auth/sso/login",
    }


@router.get("/sso/login")
def sso_login(request: Request, db: Session = Depends(get_db)):
    cfg = oidc.effective_config(db)
    if not cfg:
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
    cfg = oidc.effective_config(db)
    if not cfg:
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
    email = (claims.get("email") or "").strip().lower()
    sub = claims.get("sub")

    # Auth events carry the caller's origin, as the app's do — the panel's audit
    # log is its compliance artifact, and "who signed in from where" is the first
    # question asked after an incident.
    ip_address = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")

    def deny(reason: str, username: str | None = None):
        audit.record(db, username or actor, "auth.sso_denied", None,
                     email=email or None, reason=reason,
                     ip_address=ip_address, user_agent=user_agent)
        db.commit()
        return RedirectResponse(f"{front}/?sso_error={reason}", status_code=302)

    # The app distinguishes these three outcomes, and so do we: telling a
    # disabled operator "you aren't authorized, ask an admin to add you" sends
    # both them and the admin looking for a row that already exists.
    if not email:
        return deny("no_email")

    # App model: the operator must already exist as a User, matched by email.
    # Identity is federated; access is granted explicitly (Setup → Users), never
    # auto-provisioned from IdP membership.
    user = db.execute(
        select(User).where(func.lower(User.email) == email)
    ).scalar_one_or_none()
    if user is None:
        return deny("not_provisioned")
    if not user.is_active:
        return deny("account_disabled", username=user.username)

    if sub:
        user.oidc_sub = sub
    if not user.full_name:
        user.full_name = claims.get("name") or claims.get("full_name")
    user.last_login_at = utcnow()
    audit.record(db, user.username, "auth.sso_login", user.username,
                 provider=cfg.provider, ip_address=ip_address, user_agent=user_agent,
                 # The app records the IdP's authentication-method reference so an
                 # auditor can tell whether MFA was actually used.
                 amr=claims.get("amr"))
    token = create_access_token({"sub": user.username, "role": user.role})
    db.commit()

    # Hand the app-style JWT bearer back to the SPA (stored in localStorage).
    return RedirectResponse(f"{front}/?token={token}", status_code=302)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(settings.session_cookie_name, path="/")
    return {"ok": True}
