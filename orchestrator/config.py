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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
