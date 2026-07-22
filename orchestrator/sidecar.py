"""oauth2-proxy sidecar config generator (SSO + MFA in front of the panel).

The panel already trusts identity/group headers from an upstream OIDC proxy
(``OPERATOR_HEADER`` / ``ROLES_HEADER`` → RBAC). This renders the config for that
proxy — `oauth2-proxy` — straight from the federation the operator already
entered in the panel (``FederationConfig``), so the two can't drift:

- oauth2-proxy authenticates every request against the host IdP (Login.gov,
  Okta-for-Gov, Entra Gov) — **MFA is enforced by that IdP** and oauth2-proxy
  can additionally require it via ``--allowed-groups`` / an ``amr`` acr policy.
- On success it injects ``X-Forwarded-User`` and ``X-Forwarded-Groups``, which
  the panel maps to a role. No panel route is reachable un-authenticated.

The client secret is **not** emitted into the returned config — it's referenced
as an env var (``OAUTH2_PROXY_CLIENT_SECRET``) that the deployment injects from
the same secret manager the panel uses. The rendered text is safe to display.
"""

from orchestrator.config import settings
from orchestrator.models import FederationConfig


def _cookie_secret_hint() -> str:
    return "python -c 'import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'"


def render_config(fed: FederationConfig | None, upstream: str = "http://panel:8100") -> dict:
    """Render an oauth2-proxy.cfg + a compose snippet from the federation config.
    Secrets are referenced as env vars, never inlined."""
    issuer = (fed.issuer if fed else "") or "https://idp.example.gov"
    client_id = (fed.client_id if fed else "") or "REPLACE_WITH_CLIENT_ID"
    groups_claim = (fed.groups_claim if fed else "") or "groups"
    public_url = settings.panel_public_url or "https://panel.example.gov"
    # Groups that may sign in — the union of the mapped groups the panel knows
    # about (so only recognized operators pass the proxy at all).
    allowed_groups = sorted((fed.group_role_map or {}).keys()) if fed else []

    cfg_lines = [
        "# oauth2-proxy config — rendered by the Pinpoint 311 panel from its",
        "# federation settings. Client secret + cookie secret come from env.",
        f'provider = "oidc"',
        f'oidc_issuer_url = "{issuer}"',
        f'client_id = "{client_id}"',
        'client_secret = "${OAUTH2_PROXY_CLIENT_SECRET}"',
        'cookie_secret = "${OAUTH2_PROXY_COOKIE_SECRET}"',
        'email_domains = ["*"]',
        f'redirect_url = "{public_url.rstrip("/")}/oauth2/callback"',
        f'upstreams = ["{upstream}"]',
        "reverse_proxy = true",
        # Pass identity + groups to the panel; these are exactly what its RBAC reads.
        "pass_user_headers = true",
        "set_xauthrequest = true",
        'skip_provider_button = true',
        f'oidc_groups_claim = "{groups_claim}"',
        # Enforce a session lifetime and secure cookies.
        f'cookie_expire = "{settings.session_ttl_minutes}m"',
        "cookie_secure = true",
        "cookie_httponly = true",
        'cookie_samesite = "lax"',
    ]
    if allowed_groups:
        rendered = ", ".join(f'"{g}"' for g in allowed_groups)
        cfg_lines.append(f"allowed_groups = [{rendered}]")
    cfg = "\n".join(cfg_lines) + "\n"

    compose = f"""\
# Front the panel with SSO + MFA. Run with:  docker compose --profile sso up -d
# oauth2-proxy authenticates every request against the IdP (MFA enforced there)
# and injects X-Forwarded-User / X-Forwarded-Groups for the panel's RBAC.
services:
  oauth2-proxy:
    image: quay.io/oauth2-proxy/oauth2-proxy:v7.6.0
    profiles: ["sso"]
    restart: unless-stopped
    command: ["--config=/etc/oauth2-proxy.cfg", "--http-address=0.0.0.0:4180"]
    volumes:
      - ./oauth2-proxy.cfg:/etc/oauth2-proxy.cfg:ro
    environment:
      OAUTH2_PROXY_CLIENT_SECRET: ${{OAUTH2_PROXY_CLIENT_SECRET:?set from your secret manager}}
      OAUTH2_PROXY_COOKIE_SECRET: ${{OAUTH2_PROXY_COOKIE_SECRET:?generate: {_cookie_secret_hint()}}}
    ports:
      - "0.0.0.0:443:4180"
    depends_on:
      - panel
"""

    return {
        "provider": (fed.provider if fed else "oidc") or "oidc",
        "issuer": issuer,
        "client_id": client_id,
        "allowed_groups": allowed_groups,
        "config": cfg,
        "compose": compose,
        "note": (
            "MFA is enforced by the IdP. The client secret is injected from your "
            "secret manager as OAUTH2_PROXY_CLIENT_SECRET and is never rendered here. "
            "The panel already trusts X-Forwarded-User/Groups (OPERATOR_HEADER / "
            "ROLES_HEADER) — set those to X-Forwarded-User / X-Forwarded-Groups."
        ),
    }
