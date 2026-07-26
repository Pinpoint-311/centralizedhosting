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


def user_from_request(request: Request, db: Session) -> Optional[User]:
    """Resolve the operator from a bearer JWT, or None if absent/invalid. Never
    raises — callers that require a user use ``get_current_user`` instead."""
    token = bearer_token(request)
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.panel_secret_key, algorithms=[_ALGO])
    except PyJWTError:
        return None
    if payload.get("purpose"):
        # Single-purpose tokens (onboarding links) aren't session tokens.
        return None
    username = payload.get("sub")
    if not username:
        return None
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    return user


# ---------------------------------------------------------------- dependencies

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Require a valid bearer JWT for a user-management route."""
    user = user_from_request(request, db)
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# Single role: every active user is admin-equivalent, so admin == authenticated.
get_current_admin = get_current_user
