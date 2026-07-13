"""Key-responsibility catalog — who provides each external API key.

Two tiers:

- **Infrastructure keys** (`secrets_policy.PLATFORM_MANAGED_KEYS`): always
  state-owned, non-negotiable — `SECRET_KEY`, DB creds, KMS refs, backups,
  domain. These never appear here because there is nothing to decide.

- **Assignable services** (below): for each, the state decides — per town, or
  via a global default — whether IT provides the credential centrally
  (`"state"`, brokered by the panel and injected at provision time) or the
  town enters it in its own instance (`"town"`). Set once; the secret broker
  and provisioner honor it from then on.

This is the data behind the panel's "who owns which API key" matrix.
"""

STATE = "state"
TOWN = "town"
OWNERS = (STATE, TOWN)

# id            → the service category shown in the matrix
# label         → human name
# description   → one line of help
# keys          → the env/secret key names the app actually reads
# default_owner → who provides it unless the state overrides
# state_hint    → why a state might centralize it (shown in the UI)
ASSIGNABLE_SERVICES = [
    {
        "id": "maps",
        "label": "Google Maps",
        "description": "Geocoding, static maps, and map tiles for the resident portal.",
        "keys": ["GOOGLE_MAPS_API_KEY"],
        "default_owner": TOWN,
        "state_hint": "States often hold an enterprise Maps/GIS agreement and bill it centrally.",
    },
    {
        "id": "ai",
        "label": "AI analysis (Vertex / Gemini)",
        "description": "Automatic request triage, priority scoring, and summaries.",
        "keys": ["AI_PROVIDER_API_KEY"],
        "default_owner": TOWN,
        "state_hint": "State-funded AI so small towns get triage without their own contract.",
    },
    {
        "id": "translation",
        "label": "Translation",
        "description": "Multi-language resident intake and staff replies.",
        "keys": ["GOOGLE_TRANSLATE_API_KEY"],
        "default_owner": TOWN,
        "state_hint": "Shared translation quota across the fleet.",
    },
    {
        "id": "email_smtp",
        "label": "Email (SMTP)",
        "description": "Outbound notifications to residents and staff.",
        "keys": ["SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM_EMAIL"],
        "default_owner": TOWN,
        "state_hint": "A state relay (e.g. a gov SMTP gateway) for every town.",
    },
    {
        "id": "sms_twilio",
        "label": "SMS (Twilio)",
        "description": "Text-message alerts for staff and residents.",
        "keys": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"],
        "default_owner": TOWN,
        "state_hint": "Centralized messaging contract; towns usually run their own.",
    },
    {
        "id": "identity_sso",
        "label": "Staff SSO (identity)",
        "description": "Single sign-on for municipal staff logins.",
        "keys": ["AUTH0_DOMAIN", "AUTH0_CLIENT_ID", "AUTH0_CLIENT_SECRET"],
        "default_owner": TOWN,
        "state_hint": "A state identity tenant (Okta-for-Gov / Entra Gov) all towns federate to.",
    },
    {
        "id": "sentry",
        "label": "Error monitoring (Sentry)",
        "description": "Application error tracking and alerting.",
        "keys": ["SENTRY_DSN"],
        "default_owner": STATE,
        "state_hint": "One state Sentry org gives the hosting team fleet-wide visibility.",
    },
]

_BY_ID = {s["id"]: s for s in ASSIGNABLE_SERVICES}
_KEY_TO_SERVICE = {k: s["id"] for s in ASSIGNABLE_SERVICES for k in s["keys"]}


def default_assignments() -> dict[str, str]:
    return {s["id"]: s["default_owner"] for s in ASSIGNABLE_SERVICES}


def normalize_assignments(raw: dict | None) -> dict[str, str]:
    """Merge stored overrides onto the catalog defaults, dropping unknown
    services and invalid owners."""
    merged = default_assignments()
    for service_id, owner in (raw or {}).items():
        if service_id in _BY_ID and owner in OWNERS:
            merged[service_id] = owner
    return merged


def service_for_key(key_name: str) -> dict | None:
    sid = _KEY_TO_SERVICE.get(key_name.strip().upper())
    return _BY_ID.get(sid) if sid else None


def state_provided_keys(assignments: dict[str, str]) -> set[str]:
    """Every env key the state brokers for a tenant, given its assignments."""
    keys: set[str] = set()
    for service_id, owner in normalize_assignments(assignments).items():
        if owner == STATE:
            keys.update(_BY_ID[service_id]["keys"])
    return keys
