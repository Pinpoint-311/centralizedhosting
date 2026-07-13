"""Key-responsibility catalog — who provides each external API key.

Ownership is one of three modes:

- ``town``           — the town owns it and enters it in its own instance; it
                       never touches the panel.
- ``state_shared``   — the state enters ONE credential at the panel (the shared
                       pool, ``StateCredential``) and every town set to shared
                       plugs into that same value. Best for services that are
                       naturally one endpoint (a state SSO tenant, mail relay,
                       error-monitoring org).
- ``state_per_town`` — the state owns it but supplies a DISTINCT value per town,
                       entered per town. Best where billing attribution, quota
                       isolation, and blast-radius matter (Maps, AI, SMS).

Infrastructure keys (``secrets_policy.PLATFORM_MANAGED_KEYS``) are always
state-owned and non-negotiable, so they never appear here.

Per-service defaults tell a coherent story:
- SSO/identity and SMS default to the **town** (their IdP, their phone
  number/brand/10DLC are town-specific) — but the state *can* help by offering
  a shared tenant/account, so ``state_shared`` is available.
- Maps and AI default to **state_per_town** (metered spend the state wants
  attributable + quota-isolated per town).
- Translation, SMTP, and Sentry default to **state_shared** (low-stakes or
  inherently one shared endpoint).
"""

TOWN = "town"
STATE_SHARED = "state_shared"
STATE_PER_TOWN = "state_per_town"
OWNERS = (TOWN, STATE_SHARED, STATE_PER_TOWN)

# Legacy values from the earlier two-way model → three-way equivalents.
_LEGACY = {"state": STATE_PER_TOWN}


def owner_is_state(owner: str) -> bool:
    return owner in (STATE_SHARED, STATE_PER_TOWN)


# id            → the service category shown in the matrix
# label         → human name
# description   → one line of help
# keys          → the env/secret key names the app actually reads
# default_owner → who provides it unless the state overrides
# state_hint    → why a state might centralize it (shown when state-owned)
ASSIGNABLE_SERVICES = [
    {
        "id": "maps",
        "label": "Google Maps",
        "description": "Geocoding, static maps, and map tiles for the resident portal.",
        "keys": ["GOOGLE_MAPS_API_KEY"],
        "default_owner": STATE_PER_TOWN,
        "state_hint": "State enterprise Maps/GIS agreement, billed centrally with per-town attribution.",
    },
    {
        "id": "ai",
        "label": "AI analysis (Vertex / Gemini)",
        "description": "Automatic request triage, priority scoring, and summaries.",
        "keys": ["AI_PROVIDER_API_KEY"],
        "default_owner": STATE_PER_TOWN,
        "state_hint": "State-funded AI with per-town chargeback and quota isolation.",
    },
    {
        "id": "translation",
        "label": "Translation",
        "description": "Multi-language resident intake and staff replies.",
        "keys": ["GOOGLE_TRANSLATE_API_KEY"],
        "default_owner": STATE_SHARED,
        "state_hint": "One shared translation quota across the whole program.",
    },
    {
        "id": "email_smtp",
        "label": "Email (SMTP)",
        "description": "Outbound notifications to residents and staff.",
        "keys": ["SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM_EMAIL"],
        "default_owner": STATE_SHARED,
        "state_hint": "A single state mail relay (gov SMTP gateway) for every town.",
    },
    {
        "id": "sms_twilio",
        "label": "SMS (Twilio)",
        "description": "Text-message alerts for staff and residents.",
        "keys": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"],
        "default_owner": TOWN,
        "state_hint": "State Twilio contract with a per-town subaccount/number; towns often keep their own.",
    },
    {
        "id": "identity_sso",
        "label": "Staff SSO (identity)",
        "description": "Single sign-on for municipal staff logins.",
        "keys": ["AUTH0_DOMAIN", "AUTH0_CLIENT_ID", "AUTH0_CLIENT_SECRET"],
        "default_owner": TOWN,
        "state_hint": "Optional state identity tenant (Okta-for-Gov / Entra Gov) that towns without their own IdP can federate to.",
    },
    {
        "id": "sentry",
        "label": "Error monitoring (Sentry)",
        "description": "Application error tracking and alerting.",
        "keys": ["SENTRY_DSN"],
        "default_owner": STATE_SHARED,
        "state_hint": "One state Sentry org gives the hosting team program-wide visibility.",
    },
]

_BY_ID = {s["id"]: s for s in ASSIGNABLE_SERVICES}
_KEY_TO_SERVICE = {k: s["id"] for s in ASSIGNABLE_SERVICES for k in s["keys"]}


def default_assignments() -> dict[str, str]:
    return {s["id"]: s["default_owner"] for s in ASSIGNABLE_SERVICES}


def normalize_assignments(raw: dict | None) -> dict[str, str]:
    """Merge stored overrides onto the catalog defaults, translating legacy
    values and dropping unknown services / invalid owners."""
    merged = default_assignments()
    for service_id, owner in (raw or {}).items():
        owner = _LEGACY.get(owner, owner)
        if service_id in _BY_ID and owner in OWNERS:
            merged[service_id] = owner
    return merged


def service_for_key(key_name: str) -> dict | None:
    sid = _KEY_TO_SERVICE.get(key_name.strip().upper())
    return _BY_ID.get(sid) if sid else None


def owner_of_key(assignments: dict[str, str], key_name: str) -> str | None:
    """The ownership mode governing a given env key, or None if it isn't an
    assignable-service key."""
    service = service_for_key(key_name)
    if not service:
        return None
    return normalize_assignments(assignments).get(service["id"])


def state_provided_keys(assignments: dict[str, str]) -> set[str]:
    """Every env key the state brokers for a tenant (shared or per-town)."""
    keys: set[str] = set()
    for service_id, owner in normalize_assignments(assignments).items():
        if owner_is_state(owner):
            keys.update(_BY_ID[service_id]["keys"])
    return keys


def shared_keys(assignments: dict[str, str]) -> set[str]:
    """Env keys sourced from the shared state credential pool for a tenant."""
    keys: set[str] = set()
    for service_id, owner in normalize_assignments(assignments).items():
        if owner == STATE_SHARED:
            keys.update(_BY_ID[service_id]["keys"])
    return keys


def all_assignable_keys() -> set[str]:
    return set(_KEY_TO_SERVICE.keys())
