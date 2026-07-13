from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Panel configuration. Every value is env-overridable (upper-cased name)."""

    # Panel's own persistence + crypto. PANEL_SECRET_KEY encrypts brokered
    # secrets at rest and signs break-glass tokens — set a strong unique value.
    panel_database_url: str = "sqlite:///./panel.db"
    panel_secret_key: str = "dev-panel-secret-change-me"
    # Operator API auth. Empty -> the API fails closed (503 on every call).
    panel_api_token: str = ""
    # In production the panel must sit behind an OIDC/SSO reverse proxy that
    # authenticates each operator and sets a trusted identity header (e.g.
    # X-Forwarded-User). Name it here and the audit trail records the real
    # operator instead of a generic label. The shared token alone is NOT
    # sufficient authZ for government production — see GOVERNMENT_PRODUCTION.md.
    operator_header: str = ""

    # RBAC. Roles: viewer < operator < approver < admin. The effective role is
    # derived from a trusted groups header the OIDC/SSO proxy sets
    # (ROLES_HEADER, e.g. "X-Forwarded-Groups"), mapped via ROLE_GROUP_MAP
    # (JSON, e.g. '{"pp311-admins":"admin","pp311-ops":"operator"}'). When no
    # groups header/mapping is present, every authenticated operator gets
    # DEFAULT_OPERATOR_ROLE. Default "admin" keeps single-token dev/standalone
    # deployments fully functional; government deployments set this to "viewer"
    # (or "operator") and grant higher roles via group membership.
    default_operator_role: str = "admin"
    roles_header: str = ""
    role_group_map: str = ""

    # Panel-secret key management. "local" derives the encryption key from
    # PANEL_SECRET_KEY (dev/standalone). Government production should wrap a
    # generated data key with a FedRAMP/StateRAMP KMS — see key_provider.py and
    # GOVERNMENT_PRODUCTION.md. PANEL_KEK_VERSION supports rotation.
    key_provider: str = "local"
    panel_kek_version: int = 1

    # Supply chain. When true, provisioning refuses to deploy a release that
    # isn't pinned to an immutable digest (image@sha256:…) — the government
    # posture. Signature verification is a deployment admission control
    # (cosign/Kyverno); documented in GOVERNMENT_PRODUCTION.md.
    require_signed_images: bool = False

    # Fleet identity
    base_domain: str = "311.example.gov"
    backend_image: str = "ghcr.io/pinpoint-311/pinpoint-311-backend"
    frontend_image: str = "ghcr.io/pinpoint-311/pinpoint-311-frontend"

    # Where per-town Compose stacks are rendered (MVP deployment shape).
    tenant_root: Path = Path("./tenants")
    # When False the panel only renders stacks + records intent (safe default
    # for dev). When True it also runs `docker compose up -d` and calls the
    # town's provisioning API after deploy.
    apply_stacks: bool = False

    # Loopback port allocation for town backends/frontends on the managed host.
    base_backend_port: int = 9300
    base_frontend_port: int = 9800

    # Release management
    canary_count: int = 1

    # Break-glass grants are time-boxed; requests above this are clamped.
    break_glass_max_minutes: int = 60

    telemetry_timeout_seconds: float = 5.0

    # Optional Slack-compatible webhook for new monitoring alerts (best-effort).
    alert_webhook_url: str = ""
    # Background alert-evaluation cadence (seconds); 0 disables the loop.
    alert_poll_seconds: int = 0

    # Public self-service hosting-request intake. Off by default (adds an
    # unauthenticated endpoint); enable only behind rate-limiting/CAPTCHA.
    public_requests_enabled: bool = False

    # Region grouping (generic — not any specific state). REGION_LABEL is the
    # display term ("County", "Region", "District"); REGIONS is an optional
    # comma-separated pick-list for intake (empty = free text).
    region_label: str = "County"
    regions: str = ""

    # Analytics surfaced back to towns are aggregated to the region level with a
    # minimum number of contributing towns, so a region can't be narrowed to one.
    analytics_min_cell: int = 3

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
