"""B5 — the platform/tenant secret split, enforced from the panel side.

Mirror of the app-side split defined in ORCHESTRATOR_PLAN.md A1: the state
owns infrastructure keys; the town owns provider/branding keys. The panel
brokers ONLY the platform-managed set. Tenant-managed keys (AI, translation,
identity, SMTP/SMS, branding) never touch the panel — towns enter those in
their own instance, and the app rejects platform-managed writes when
MANAGED_MODE=true.
"""

PLATFORM_MANAGED_KEYS = {
    "SECRET_KEY",
    "DATABASE_URL",
    "DB_PASSWORD",
    "REDIS_URL",
    "PROVISIONING_TOKEN",
    "GOOGLE_CLOUD_PROJECT",
    "KMS_KEY_RING",
    "KMS_KEY_ID",
    "KMS_LOCATION",
    "AZURE_KEYVAULT_URL",
    "DOMAIN",
}

PLATFORM_MANAGED_PREFIXES = ("BACKUP_",)


def is_platform_managed(key_name: str) -> bool:
    key = key_name.strip().upper()
    return key in PLATFORM_MANAGED_KEYS or key.startswith(PLATFORM_MANAGED_PREFIXES)


def assert_platform_managed(key_name: str) -> str:
    """Normalize and validate a key the panel is asked to broker."""
    key = key_name.strip().upper()
    if not is_platform_managed(key):
        raise ValueError(
            f"'{key}' is tenant-managed — provider, integration, and branding "
            "keys never touch the panel. The town sets them in its own instance."
        )
    return key
