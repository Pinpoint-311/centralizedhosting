"""Operator authentication — ported from the Pinpoint 311 app's core/auth.py,
adapted to the control plane (sync SQLAlchemy, PANEL_SECRET_KEY, single role).

Humans authenticate with a bearer JWT (Authorization: Bearer <token>) minted
either by the SSO callback (identity matched to a User by email) or by password
login for the first admin / break-fix. The token is HS256-signed with
PANEL_SECRET_KEY and carries ``sub`` = username. Machine/CI callers continue to
use X-Panel-Token (see security.require_role, which accepts either).
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from jwt.exceptions import PyJWTError
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.config import settings
from orchestrator.db import get_db
from orchestrator.models import User

_ALGO = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------------------------------------------------------------- passwords

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


# ---------------------------------------------------------------- JWT

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=max(1, settings.session_ttl_minutes))
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.panel_secret_key, algorithm=_ALGO)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.panel_secret_key, algorithms=[_ALGO])
    except PyJWTError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def bearer_token(request: Request) -> Optional[str]:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def resolve_bearer_user(request: Request, db: Session) -> tuple[str, Optional[User]]:
    """Resolve the operator from a bearer JWT.

    Returns ``(state, user)`` where state is:
      ``"none"``     — no usable bearer; the caller should try its other auth paths
      ``"ok"``       — an active operator
      ``"inactive"`` — a real account that has been disabled

    The third case is separated because it is the one an admin can act on. If it
    collapsed into "none", a deactivated operator's still-valid token would fall
    through to the token/cookie paths and surface as "missing or invalid panel
    token" — which sends them chasing a credential problem they don't have.
    """
    token = bearer_token(request)
    if not token:
        return ("none", None)
    try:
        payload = jwt.decode(token, settings.panel_secret_key, algorithms=[_ALGO])
    except PyJWTError:
        return ("none", None)
    if payload.get("purpose"):
        # Single-purpose tokens (onboarding links) aren't session tokens.
        return ("none", None)
    username = payload.get("sub")
    if not username:
        return ("none", None)
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        return ("none", None)
    return ("ok", user) if user.is_active else ("inactive", user)


def user_from_request(request: Request, db: Session) -> Optional[User]:
    """The active operator behind a bearer JWT, or None. Never raises."""
    state, user = resolve_bearer_user(request, db)
    return user if state == "ok" else None


# ---------------------------------------------------------------- dependencies

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Require a valid bearer JWT for a user-management route.

    Mirrors the app's get_current_user, including its distinction between an
    unusable token (401) and a real but deactivated account (403) — the second
    is actionable by an admin, and collapsing both into 401 hides that.
    """
    token = bearer_token(request)
    if not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(token)  # raises 401 on a bad/expired token
    if payload.get("purpose"):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Single-purpose token cannot be used for API access",
        )
    username = payload.get("sub")
    if not username:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Could not validate credentials")
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Inactive user")
    return user


# Single role: every active user is admin-equivalent, so admin == authenticated.
get_current_admin = get_current_user
