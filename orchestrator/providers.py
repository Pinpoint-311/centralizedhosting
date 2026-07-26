"""Cloud service-provider catalogs — the capabilities a state hosts for its
towns: AI, translation, and staff identity (SSO). Ported from the Pinpoint 311
app's service-provider registries (services/ai/registry.py,
services/translation_providers.py, services/identity.py) plus the one-click
cloud profiles (api/system.py CLOUD_PROFILES).

Selection + credentials persist in the global SystemSetting store, envelope-
encrypted with the panel key. Non-secret values (project ids, endpoints, the
provider selector) are returned to the UI; secret values are write-only.
"""

from orchestrator.models import SystemSetting, utcnow
from orchestrator.security import decrypt_value, encrypt_value
from sqlalchemy.orm import Session

AI_CATALOG = {
    "vertex": {
        "name": "Google Vertex AI",
        "boundary": "Google Cloud (Assured Workloads / FedRAMP High)",
        "description": "Gemini models on Vertex AI. The default — cheapest for triage and already integrated.",
        "models": [
            {"id": "gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash-Lite (fast, cheap — recommended)"},
            {"id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash (near-Pro quality, 1M context)"},
        ],
        "default_model": "gemini-3.1-flash-lite",
        "credential_fields": [
            {"key": "VERTEX_AI_PROJECT", "label": "GCP Project ID", "secret": False},
            {"key": "VERTEX_AI_SERVICE_ACCOUNT_KEY", "label": "Service Account JSON", "secret": True},
        ],
        "field_help": {
            "VERTEX_AI_PROJECT": "Your Google Cloud project id.",
            "VERTEX_AI_SERVICE_ACCOUNT_KEY": "Optional if the host provides default credentials; otherwise paste the service-account JSON.",
        },
    },
    "azure": {
        "name": "Azure Government AI",
        "boundary": "Azure Government / GCC High (FedRAMP High / DoD)",
        "description": "Azure OpenAI (GPT models) in US government regions. Best for Microsoft/M365 states.",
        "models": [
            {"id": "gpt-4o-mini", "label": "GPT-4o mini (fast, cheap)"},
            {"id": "gpt-4o", "label": "GPT-4o (higher quality)"},
        ],
        "default_model": "gpt-4o-mini",
        "credential_fields": [
            {"key": "AZURE_OPENAI_ENDPOINT", "label": "Azure OpenAI Endpoint", "secret": False},
            {"key": "AZURE_OPENAI_API_KEY", "label": "API Key", "secret": True},
            {"key": "AZURE_OPENAI_DEPLOYMENT", "label": "Deployment name", "secret": False},
            {"key": "AZURE_OPENAI_API_VERSION", "label": "API version (optional)", "secret": False},
        ],
        "field_help": {
            "AZURE_OPENAI_ENDPOINT": "e.g. https://your-resource.openai.azure.us — the Gov-cloud endpoint.",
            "AZURE_OPENAI_API_KEY": "Key 1 or Key 2 from your Azure OpenAI resource.",
            "AZURE_OPENAI_DEPLOYMENT": "The deployment name you created for the model (acts as the model id).",
            "AZURE_OPENAI_API_VERSION": "Leave blank to use the supported default.",
        },
    },
    "bedrock": {
        "name": "AWS Bedrock",
        "boundary": "AWS GovCloud (FedRAMP High)",
        "description": "Claude and other models via Amazon Bedrock. Best for AWS GovCloud states.",
        "models": [
            {"id": "anthropic.claude-3-5-sonnet-20240620-v1:0", "label": "Claude 3.5 Sonnet (quality)"},
            {"id": "anthropic.claude-3-haiku-20240307-v1:0", "label": "Claude 3 Haiku (fast, cheap)"},
        ],
        "default_model": "anthropic.claude-3-5-sonnet-20240620-v1:0",
        "credential_fields": [
            {"key": "AWS_REGION", "label": "AWS Region", "secret": False},
            {"key": "AWS_ACCESS_KEY_ID", "label": "Access Key ID (optional)", "secret": False},
            {"key": "AWS_SECRET_ACCESS_KEY", "label": "Secret Access Key (optional)", "secret": True},
        ],
        "field_help": {
            "AWS_REGION": "e.g. us-gov-west-1. Shared across all AWS services.",
            "AWS_ACCESS_KEY_ID": "Optional — omit to use the host's instance role.",
            "AWS_SECRET_ACCESS_KEY": "Optional — omit to use the host's instance role.",
        },
    },
}

TRANSLATION_CATALOG = {
    "google": {
        "name": "Google Cloud Translation",
        "description": "Google Translate — the default; ~100+ languages.",
        "credential_fields": [
            {"key": "GOOGLE_CLOUD_PROJECT", "label": "GCP Project (uses the same GCP creds)", "secret": False},
        ],
        "field_help": {"GOOGLE_CLOUD_PROJECT": "Uses your existing Google Cloud credentials; no extra key needed."},
    },
    "azure": {
        "name": "Azure AI Translator",
        "description": "Azure Cognitive Services Translator — for Microsoft/Azure-Government stacks.",
        "credential_fields": [
            {"key": "AZURE_TRANSLATOR_KEY", "label": "Translator Key", "secret": True},
            {"key": "AZURE_TRANSLATOR_REGION", "label": "Region", "secret": False},
            {"key": "AZURE_TRANSLATOR_ENDPOINT", "label": "Endpoint (optional; .us for Gov)", "secret": False},
        ],
        "field_help": {
            "AZURE_TRANSLATOR_KEY": "Key from your Azure Translator resource.",
            "AZURE_TRANSLATOR_REGION": "e.g. usgovvirginia or eastus.",
            "AZURE_TRANSLATOR_ENDPOINT": "Leave blank for global; use the .us endpoint for Azure Government.",
        },
    },
    "aws": {
        "name": "Amazon Translate",
        "description": "AWS Translate — for AWS GovCloud stacks; uses your AWS credentials.",
        "credential_fields": [
            {"key": "AWS_REGION", "label": "AWS Region", "secret": False},
            {"key": "AWS_ACCESS_KEY_ID", "label": "Access Key ID (optional)", "secret": False},
            {"key": "AWS_SECRET_ACCESS_KEY", "label": "Secret Access Key (optional)", "secret": True},
        ],
        "field_help": {
            "AWS_REGION": "e.g. us-gov-west-1.",
            "AWS_ACCESS_KEY_ID": "Leave blank to use the instance role / default credential chain.",
            "AWS_SECRET_ACCESS_KEY": "Leave blank to use the instance role / default credential chain.",
        },
    },
}

IDENTITY_CATALOG = {
    "auth0": {
        "name": "Auth0",
        "description": "Auth0 by Okta — the default. Works with any Auth0 tenant.",
        "credential_fields": [
            {"key": "AUTH0_DOMAIN", "label": "Auth0 Domain", "secret": False},
            {"key": "AUTH0_CLIENT_ID", "label": "Client ID", "secret": False},
            {"key": "AUTH0_CLIENT_SECRET", "label": "Client Secret", "secret": True},
        ],
        "field_help": {
            "AUTH0_DOMAIN": "e.g. yourorg.us.auth0.com",
            "AUTH0_CLIENT_ID": "From your Auth0 Regular Web Application.",
            "AUTH0_CLIENT_SECRET": "From the same Auth0 application.",
        },
    },
    "entra": {
        "name": "Microsoft Entra ID",
        "description": "Azure AD / Entra ID — ideal for states already on Microsoft 365.",
        "credential_fields": [
            {"key": "ENTRA_TENANT_ID", "label": "Directory (tenant) ID", "secret": False},
            {"key": "ENTRA_CLIENT_ID", "label": "Application (client) ID", "secret": False},
            {"key": "ENTRA_CLIENT_SECRET", "label": "Client Secret", "secret": True},
            {"key": "ENTRA_AUTHORITY", "label": "Authority host (optional; Gov = login.microsoftonline.us)", "secret": False},
        ],
        "field_help": {
            "ENTRA_TENANT_ID": "Directory (tenant) ID from the Entra admin center.",
            "ENTRA_CLIENT_ID": "App registration's Application (client) ID.",
            "ENTRA_CLIENT_SECRET": "A client secret from the app registration.",
            "ENTRA_AUTHORITY": "Blank for commercial; login.microsoftonline.us for Azure Government.",
        },
    },
    "okta": {
        "name": "Okta",
        "description": "Okta / Okta for Government (FedRAMP).",
        "credential_fields": [
            {"key": "OKTA_ISSUER", "label": "Issuer URL", "secret": False},
            {"key": "OKTA_CLIENT_ID", "label": "Client ID", "secret": False},
            {"key": "OKTA_CLIENT_SECRET", "label": "Client Secret", "secret": True},
        ],
        "field_help": {
            "OKTA_ISSUER": "e.g. https://your-org.okta.com/oauth2/default",
            "OKTA_CLIENT_ID": "From your Okta OIDC Web app.",
            "OKTA_CLIENT_SECRET": "From the same Okta app.",
        },
    },
    "oidc": {
        "name": "Generic OIDC",
        "description": "Any OpenID Connect provider via its issuer URL.",
        "credential_fields": [
            {"key": "OIDC_ISSUER", "label": "Issuer URL", "secret": False},
            {"key": "OIDC_CLIENT_ID", "label": "Client ID", "secret": False},
            {"key": "OIDC_CLIENT_SECRET", "label": "Client Secret", "secret": True},
        ],
        "field_help": {
            "OIDC_ISSUER": "The provider's issuer (must serve /.well-known/openid-configuration).",
            "OIDC_CLIENT_ID": "OAuth client id.",
            "OIDC_CLIENT_SECRET": "OAuth client secret.",
        },
    },
}

CATALOGS = {"ai": AI_CATALOG, "translation": TRANSLATION_CATALOG, "identity": IDENTITY_CATALOG}
SELECTOR_KEY = {"ai": "AI_PROVIDER", "translation": "TRANSLATION_PROVIDER", "identity": "IDENTITY_PROVIDER"}
DEFAULT_PROVIDER = {"ai": "vertex", "translation": "google", "identity": "auth0"}
MODEL_KEY = "AI_MODEL"

CLOUD_PROFILES = {
    "google": {
        "label": "Google Cloud", "boundary": "Google Cloud — FedRAMP High / StateRAMP",
        "ai": "vertex", "translation": "google", "secrets": "google", "kms": "google",
        "email": "smtp", "sms": "", "identity_recommended": "auth0",
    },
    "azure": {
        "label": "Microsoft Azure (Government)", "boundary": "Azure Government / GCC High — FedRAMP High, DoD IL4/5",
        "ai": "azure", "translation": "azure", "secrets": "azure", "kms": "azure",
        "email": "acs", "sms": "acs", "identity_recommended": "entra",
    },
    "aws": {
        "label": "Amazon Web Services (GovCloud)", "boundary": "AWS GovCloud — FedRAMP High, DoD IL4/5",
        "ai": "bedrock", "translation": "aws", "secrets": "aws", "kms": "aws",
        "email": "ses", "sms": "sns", "identity_recommended": "oidc",
    },
}


# ---------------------------------------------------------------- settings store

def get_setting(db: Session, key: str) -> str | None:
    row = db.get(SystemSetting, key)
    if not row:
        return None
    try:
        return decrypt_value(row.value_encrypted)
    except Exception:  # noqa: BLE001
        return None


def set_setting(db: Session, key: str, value: str, is_secret: bool = False) -> None:
    enc = encrypt_value(value)
    row = db.get(SystemSetting, key)
    if row:
        row.value_encrypted = enc
        row.is_secret = is_secret
        row.updated_at = utcnow()
    else:
        db.add(SystemSetting(key_name=key, value_encrypted=enc, is_secret=is_secret))


# ---------------------------------------------------------------- catalog helpers

def _all_fields(capability: str) -> dict:
    out: dict[str, dict] = {}
    for meta in CATALOGS[capability].values():
        for f in meta["credential_fields"]:
            out[f["key"]] = f
    return out


def selected_provider(db: Session, capability: str) -> str:
    return get_setting(db, SELECTOR_KEY[capability]) or DEFAULT_PROVIDER[capability]


def catalog_for_api(db: Session, capability: str) -> dict:
    cat = CATALOGS[capability]
    selected = selected_provider(db, capability)
    configured: dict[str, bool] = {}
    values: dict[str, str] = {}
    for key, f in _all_fields(capability).items():
        v = get_setting(db, key)
        if v:
            configured[key] = True
            if not f.get("secret"):
                values[key] = v
    out = {
        "capability": capability,
        "providers": [{"provider": k, **v} for k, v in cat.items()],
        "selected": selected,
        "configured": configured,
        "values": values,
    }
    if capability == "ai":
        out["model"] = get_setting(db, MODEL_KEY) or cat.get(selected, {}).get("default_model")
    return out


def save_provider(db: Session, capability: str, provider: str, model: str | None, credentials: dict) -> None:
    cat = CATALOGS[capability]
    if provider not in cat:
        raise ValueError(f"Unknown {capability} provider: {provider}")
    set_setting(db, SELECTOR_KEY[capability], provider, is_secret=False)
    if capability == "ai" and model:
        if model in {m["id"] for m in cat[provider]["models"]}:
            set_setting(db, MODEL_KEY, model, is_secret=False)
    fields = {f["key"]: f for f in cat[provider]["credential_fields"]}
    for key, val in (credentials or {}).items():
        if key in fields and str(val).strip():
            set_setting(db, key, str(val).strip(), is_secret=bool(fields[key].get("secret")))


def provider_status(db: Session, capability: str) -> dict:
    """A light 'test': are the required (non-optional) credentials present?"""
    provider = selected_provider(db, capability)
    meta = CATALOGS[capability].get(provider)
    if not meta:
        return {"ok": False, "message": "No provider selected"}
    missing = [
        f["label"] for f in meta["credential_fields"]
        if "optional" not in f["label"].lower() and not get_setting(db, f["key"])
    ]
    if missing:
        return {"ok": False, "message": f"Missing credentials: {', '.join(missing)}"}
    return {"ok": True, "message": f"{meta['name']} is configured"}


def cloud_profile_state(db: Session) -> dict:
    ai, tr = selected_provider(db, "ai"), selected_provider(db, "translation")
    current = next(
        (pid for pid, p in CLOUD_PROFILES.items() if p["ai"] == ai and p["translation"] == tr),
        None,
    )
    return {
        "current": current,
        "components": {"ai": ai, "translation": tr, "identity": selected_provider(db, "identity")},
        "profiles": [{"id": k, **v} for k, v in CLOUD_PROFILES.items()],
    }


def apply_cloud_profile(db: Session, profile_id: str, apply_identity: bool = False) -> dict:
    p = CLOUD_PROFILES.get(profile_id)
    if not p:
        raise ValueError("Unknown cloud profile")
    set_setting(db, SELECTOR_KEY["ai"], p["ai"])
    set_setting(db, SELECTOR_KEY["translation"], p["translation"])
    if apply_identity and p.get("identity_recommended"):
        set_setting(db, SELECTOR_KEY["identity"], p["identity_recommended"])
    return cloud_profile_state(db)
