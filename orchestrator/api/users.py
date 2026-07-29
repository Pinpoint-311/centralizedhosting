"""Operator (User) management + password login — ported from the Pinpoint 311
app's api/users.py + api/auth.py, adapted to the control plane.

Access model (per the operator's choice): a single role. Every active user is
admin-equivalent, so there's no role picker — management is just add / remove /
enable operators. Identity normally comes from SSO (auth_sso mints the bearer by
matching email to a User); password login exists for the first admin and
break-fix. User-management routes are guarded by the panel's ``require_admin``,
which accepts the app JWT, the SSO cookie, OR X-Panel-Token — so the token
holder can create the first operators before anyone can log in.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orchestrator import audit, user_auth
from orchestrator.db import get_db
from orchestrator.models import User, utcnow
from orchestrator.security import require_admin, resolve_role

router = APIRouter(prefix="/api", tags=["users"])


# ---------------------------------------------------------------- schemas

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: EmailStr
    full_name: str | None = None


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = None
    is_active: bool | None = None


class PasswordSet(BaseModel):
    password: str = Field(min_length=10, max_length=200)


class LoginIn(BaseModel):
    username: str
    password: str


def _out(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "full_name": u.full_name,
        "role": u.role,
        "is_active": u.is_active,
        "has_password": bool(u.hashed_password),
        "auth": "sso" if u.oidc_sub else ("password" if u.hashed_password else "invited"),
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


# ---------------------------------------------------------------- CRUD

@router.get("/users")
def list_users(db: Session = Depends(get_db), _: str = Depends(require_admin)):
    rows = db.execute(select(User).order_by(User.created_at.desc())).scalars().all()
    return [_out(u) for u in rows]


@router.post("/users", status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), actor: str = Depends(require_admin)):
    """Create a new user (admin only).

    Users are created with email as their identifier. They will log in via SSO
    using their email address. No password is required as authentication is
    handled by the identity provider — one can be set later for break-fix.
    """
    uname = body.username.strip()
    email = body.email.strip().lower()
    # Same status + wording as the app's create_user.
    if db.execute(select(User).where(func.lower(User.username) == uname.lower())).scalar_one_or_none():
        raise HTTPException(400, "Username already exists")
    if db.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none():
        raise HTTPException(400, "Email already exists")
    user = User(username=uname, email=email, full_name=(body.full_name or None),
                hashed_password=None,  # No password for SSO users
                role="admin", is_active=True)
    db.add(user)
    audit.record(db, actor, "user.created", uname, email=email)
    db.commit()
    db.refresh(user)
    return _out(user)


@router.get("/users/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    """Get user by ID (admin only)."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return _out(user)


@router.put("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db),
                actor: str = Depends(require_admin)):
    """Update user (admin only)."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    # The app's setattr loop over exclude_unset fields, with the two guards the
    # control plane needs: email uniqueness, and normalising email to lowercase
    # (SSO matches operators on it, so a case variant must not create a rival row).
    update_data = body.model_dump(exclude_unset=True)
    if update_data.get("email"):
        email = update_data["email"].strip().lower()
        clash = db.execute(
            select(User).where(func.lower(User.email) == email, User.id != user_id)
        ).scalar_one_or_none()
        if clash:
            raise HTTPException(400, "Email already exists")
        update_data["email"] = email
    for field, value in update_data.items():
        if value is not None:
            setattr(user, field, value)

    audit.record(db, actor, "user.updated", user.username, fields=sorted(update_data.keys()))
    db.commit()
    db.refresh(user)
    return _out(user)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db),
                actor: str = Depends(require_admin)):
    """Delete user (admin only)."""
    # Self-check by id first, as the app does. Comparing ids (not usernames)
    # matters here: a machine caller authenticated by X-Panel-Token has no User
    # row, so there is no account of its own to protect.
    current = user_auth.user_from_request(request, db)
    if current is not None and current.id == user_id:
        raise HTTPException(400, "Cannot delete yourself")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    db.delete(user)
    audit.record(db, actor, "user.deleted", user.username)
    db.commit()


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, body: PasswordSet, db: Session = Depends(get_db),
                 actor: str = Depends(require_admin)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    """Reset user password (admin only)."""
    user.hashed_password = user_auth.get_password_hash(body.password)
    audit.record(db, actor, "user.password_set", user.username)
    db.commit()
    return _out(user)


# ---------------------------------------------------------------- login / me

def _bootstrap_gate_open(db: Session) -> bool:
    """Password sign-in is permitted ONLY when NO identity provider is
    configured (Auth0, Entra, Okta, or generic OIDC). Ported from the app's
    _bootstrap_gate_open.

    Fail-closed: gates on the *presence* of identity config, not its
    reachability, so an IdP outage cannot re-open password admin access.
    """
    from orchestrator import oidc

    return not oidc.is_identity_configured(db)


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    """First-run password sign-in, gated exactly like the app's bootstrap: it
    works only until an identity provider is configured. After that, operators
    sign in through SSO. Mints the app-style JWT bearer."""
    if not _bootstrap_gate_open(db):
        raise HTTPException(
            403,
            "Password sign-in is disabled — single sign-on is configured. "
            "Use 'Sign in with SSO'.",
        )
    user = db.execute(
        select(User).where(func.lower(User.username) == body.username.strip().lower())
    ).scalar_one_or_none()
    if not user or not user.hashed_password or not user_auth.verify_password(body.password, user.hashed_password):
        raise HTTPException(401, "Invalid username or password")
    if not user.is_active:
        raise HTTPException(403, "Account is disabled")
    user.last_login_at = utcnow()
    token = user_auth.create_access_token({"sub": user.username, "role": user.role})
    audit.record(db, user.username, "user.login", user.username, method="password",
                 ip_address=(request.client.host if request.client else "unknown"),
                 user_agent=request.headers.get("user-agent", "unknown"))
    db.commit()
    return {"access_token": token, "token_type": "bearer", "user": _out(user)}


@router.get("/auth/me")
def whoami(request: Request, db: Session = Depends(get_db)):
    """Current identity. Returns the User for a bearer/SSO login, or a synthetic
    machine identity when authenticated only by X-Panel-Token."""
    user = user_auth.user_from_request(request, db)
    if user is not None:
        return {**_out(user), "via": "user"}
    # Fall back to the panel's other auth paths (SSO cookie / X-Panel-Token).
    actor = require_admin(request=request, x_panel_token=request.headers.get("x-panel-token", ""), db=db)
    return {
        "id": None,
        "username": actor,
        "email": None,
        "full_name": None,
        "role": resolve_role(request),
        "is_active": True,
        "via": "token",
    }
