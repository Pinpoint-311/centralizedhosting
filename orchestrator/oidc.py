"""OIDC federation for panel operator SSO.

Generic OpenID Connect (authorization-code + PKCE) via discovery, so any
compliant IdP works — Auth0, Entra/Azure AD (Gov), Okta, Login.gov, Keycloak.

Set up the SAME way as the Pinpoint 311 app: an ``IDENTITY_PROVIDER`` selector
(``auth0`` | ``entra`` | ``okta`` | ``oidc``) plus the app's per-provider
credential env vars — ``AUTH0_DOMAIN``/``AUTH0_CLIENT_ID``/``AUTH0_CLIENT_SECRET``,
``ENTRA_TENANT_ID``/``ENTRA_CLIENT_ID``/``ENTRA_CLIENT_SECRET``/``ENTRA_AUTHORITY``,
``OKTA_ISSUER``/``OKTA_CLIENT_ID``/``OKTA_CLIENT_SECRET``,
``OIDC_ISSUER``/``OIDC_CLIENT_ID``/``OIDC_CLIENT_SECRET`` — with the issuer
derived exactly as the app derives it. As an alternative, the panel also lets an
admin enter the same fields in the UI (``FederationConfig``, client secret
stored envelope-encrypted). Either source produces the same effective config.
"""

import base64
import hashlib
import json
import os
import secrets as pysecrets
from dataclasses import dataclass, field

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.config import settings
from orchestrator.models import FederationConfig
from orchestrator.security import ROLES, _RANK, decrypt_value

_DISCO_CACHE: dict[str, dict] = {}


@dataclass
class EffectiveConfig:
    """Resolved SSO config from either env (app-style provider catalog) or the
    DB FederationConfig. Carries the plaintext client secret for the flow."""

    provider: str
    issuer: str
    client_id: str
    client_secret: str
    groups_claim: str = "groups"
    group_role_map: dict = field(default_factory=dict)
    default_role: str = "viewer"


def get_config(db: Session) -> FederationConfig | None:
    return db.get(FederationConfig, "default")


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _role_map_from_settings() -> dict:
    """Env-configured SSO reuses the panel's existing ROLE_GROUP_MAP for the
    group→role mapping (same var the header-based RBAC uses)."""
    if not settings.role_group_map:
        return {}
    try:
        raw = json.loads(settings.role_group_map)
        return {str(k): str(v) for k, v in raw.items() if v in ROLES}
    except Exception:
        return {}


def resolve_identity_config() -> EffectiveConfig | None:
    """Build the effective SSO config from the app's provider-catalog env vars.
    Returns None when IDENTITY_PROVIDER is unset or its credentials are missing.
    Issuer derivation matches the app exactly."""
    provider = _env("IDENTITY_PROVIDER").lower()
    if not provider:
        return None

    if provider == "auth0":
        domain, cid, sec = _env("AUTH0_DOMAIN"), _env("AUTH0_CLIENT_ID"), _env("AUTH0_CLIENT_SECRET")
        if not (domain and cid and sec):
            return None
        issuer = f"https://{domain}"
    elif provider == "entra":
        tenant, cid, sec = _env("ENTRA_TENANT_ID"), _env("ENTRA_CLIENT_ID"), _env("ENTRA_CLIENT_SECRET")
        authority = _env("ENTRA_AUTHORITY") or "login.microsoftonline.com"
        if not (tenant and cid and sec):
            return None
        issuer = f"https://{authority}/{tenant}/v2.0"
    elif provider == "okta":
        issuer, cid, sec = _env("OKTA_ISSUER"), _env("OKTA_CLIENT_ID"), _env("OKTA_CLIENT_SECRET")
        if not (issuer and cid and sec):
            return None
    elif provider == "oidc":
        issuer, cid, sec = _env("OIDC_ISSUER"), _env("OIDC_CLIENT_ID"), _env("OIDC_CLIENT_SECRET")
        if not (issuer and cid and sec):
            return None
    else:
        return None

    return EffectiveConfig(
        provider=provider,
        issuer=issuer.rstrip("/"),
        client_id=cid,
        client_secret=sec,
        groups_claim=_env("SSO_GROUPS_CLAIM") or "groups",
        group_role_map=_role_map_from_settings(),
        default_role=(settings.default_operator_role if settings.default_operator_role in ROLES else "viewer"),
    )


def _from_db(cfg: FederationConfig) -> EffectiveConfig:
    return EffectiveConfig(
        provider=cfg.provider or "oidc",
        issuer=(cfg.issuer or "").rstrip("/"),
        client_id=cfg.client_id or "",
        client_secret=decrypt_value(cfg.client_secret_encrypted) if cfg.client_secret_encrypted else "",
        groups_claim=cfg.groups_claim or "groups",
        group_role_map={str(k): v for k, v in (cfg.group_role_map or {}).items() if v in ROLES},
        default_role=cfg.default_role if cfg.default_role in ROLES else "viewer",
    )


def effective_config(db: Session) -> EffectiveConfig | None:
    """The SSO config in force: the DB FederationConfig when an admin has enabled
    it, otherwise the env provider catalog (set up exactly like the app)."""
    cfg = get_config(db)
    if cfg and cfg.enabled and cfg.issuer and cfg.client_id and cfg.client_secret_encrypted:
        return _from_db(cfg)
    return resolve_identity_config()


def is_configured(db: Session) -> bool:
    return effective_config(db) is not None


def _assert_https(url: str) -> None:
    # SSRF guard: only reach public HTTPS IdPs (allow http for localhost dev).
    if url.startswith("https://"):
        return
    if settings.panel_cookie_insecure and url.startswith("http://"):
        return
    raise ValueError("IdP issuer must be https://")


def discover(issuer: str, *, force: bool = False) -> dict:
    """Fetch (and cache) the IdP's OIDC discovery document."""
    issuer = issuer.rstrip("/")
    if not force and issuer in _DISCO_CACHE:
        return _DISCO_CACHE[issuer]
    url = f"{issuer}/.well-known/openid-configuration"
    _assert_https(url)
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url)
    resp.raise_for_status()
    meta = resp.json()
    for required in ("authorization_endpoint", "token_endpoint", "jwks_uri", "issuer"):
        if required not in meta:
            raise ValueError(f"IdP discovery missing {required}")
    _DISCO_CACHE[issuer] = meta
    return meta


def make_pkce() -> tuple[str, str]:
    verifier = pysecrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(cfg: EffectiveConfig, meta: dict, redirect_uri: str,
                  state: str, nonce: str, code_challenge: str) -> str:
    params = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid profile email",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{meta['authorization_endpoint']}?{httpx.QueryParams(params)}"


def exchange_code(cfg: EffectiveConfig, meta: dict, code: str,
                  redirect_uri: str, code_verifier: str) -> dict:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
        "code_verifier": code_verifier,
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(meta["token_endpoint"], data=data,
                           headers={"Accept": "application/json"})
    resp.raise_for_status()
    return resp.json()


def verify_id_token(cfg: EffectiveConfig, meta: dict, id_token: str, nonce: str) -> dict:
    """Verify the ID token's RS256 signature (JWKS), audience, issuer, expiry,
    and nonce. Returns the validated claims."""
    jwks = jwt.PyJWKClient(meta["jwks_uri"])
    signing_key = jwks.get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=cfg.client_id,
        issuer=meta["issuer"],
    )
    if nonce and claims.get("nonce") != nonce:
        raise ValueError("nonce mismatch")
    return claims


def role_from_claims(cfg: EffectiveConfig, claims: dict) -> str:
    """Map the operator's IdP groups/roles to the highest panel role, or the
    configured default role when nothing maps."""
    mapping = {str(k): v for k, v in (cfg.group_role_map or {}).items() if v in ROLES}
    raw = claims.get(cfg.groups_claim or "groups", [])
    if isinstance(raw, str):
        groups = [g.strip() for g in raw.replace(",", " ").split() if g.strip()]
    elif isinstance(raw, list):
        groups = [str(g) for g in raw]
    else:
        groups = []
    best = -1
    for g in groups:
        role = mapping.get(g)
        if role and _RANK[role] > best:
            best = _RANK[role]
    if best >= 0:
        return ROLES[best]
    default = cfg.default_role if cfg.default_role in ROLES else "viewer"
    return default


def operator_identity(claims: dict) -> str:
    return (claims.get("email") or claims.get("preferred_username")
            or claims.get("sub") or "sso-operator")[:150]
