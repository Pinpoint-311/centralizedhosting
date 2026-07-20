"""OIDC federation for panel operator SSO.

Generic OpenID Connect (authorization-code + PKCE) via discovery, so any
compliant IdP works — Auth0, Entra/Azure AD (Gov), Okta, Login.gov, Keycloak.
The host configures the issuer + client credentials once (FederationConfig);
the client secret is stored encrypted via the panel's secret manager.
"""

import base64
import hashlib
import secrets as pysecrets

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.config import settings
from orchestrator.models import FederationConfig
from orchestrator.security import ROLES, _RANK, decrypt_value

_DISCO_CACHE: dict[str, dict] = {}


def get_config(db: Session) -> FederationConfig | None:
    return db.get(FederationConfig, "default")


def is_configured(db: Session) -> bool:
    c = get_config(db)
    return bool(c and c.enabled and c.issuer and c.client_id and c.client_secret_encrypted)


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


def authorize_url(cfg: FederationConfig, meta: dict, redirect_uri: str,
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


def exchange_code(cfg: FederationConfig, meta: dict, code: str,
                  redirect_uri: str, code_verifier: str) -> dict:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": cfg.client_id,
        "client_secret": decrypt_value(cfg.client_secret_encrypted),
        "code_verifier": code_verifier,
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(meta["token_endpoint"], data=data,
                           headers={"Accept": "application/json"})
    resp.raise_for_status()
    return resp.json()


def verify_id_token(cfg: FederationConfig, meta: dict, id_token: str, nonce: str) -> dict:
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


def role_from_claims(cfg: FederationConfig, claims: dict) -> str:
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
