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
        # decrypt_value reads every scheme the panel has written (pii2:, akv:,
        # v<n>:, plain Fernet), so older rows keep working.
        return decrypt_value(row.value_encrypted)
    except Exception:  # noqa: BLE001
        return None


def set_setting(db: Session, key: str, value: str, is_secret: bool = False) -> None:
    """Persist a config/credential value — the app's _persist_secret path.

    Writes use plain Fernet (``encryption.encrypt``), matching the app, rather
    than the KMS envelope. That is deliberate and load-bearing: ``KMS_PROVIDER``
    itself lives in this store, and resolving it must never require a KMS round
    trip — envelope-encrypting it would make ``_kms_provider()`` recurse into
    its own decrypt path.
    """
    from orchestrator import encryption

    enc = encryption.encrypt(value)
    row = db.get(SystemSetting, key)
    if row:
        row.value_encrypted = enc
        row.is_secret = is_secret
        row.updated_at = utcnow()
    else:
        db.add(SystemSetting(key_name=key, value_encrypted=enc, is_secret=is_secret))


def secrets_provider() -> str:
    """Which secret store backs the panel — the app's _secrets_provider()."""
    import os

    val = os.getenv("SECRETS_PROVIDER")
    if val:
        return val.strip().lower()
    try:
        from orchestrator.encryption import _get_config_sync

        return (_get_config_sync("SECRETS_PROVIDER") or "google").strip().lower()
    except Exception:  # noqa: BLE001
        return "google"


# ---------------------------------------------------------------- catalog helpers

def _all_fields(capability: str) -> dict:
    out: dict[str, dict] = {}
    for meta in CATALOGS[capability].values():
        for f in meta["credential_fields"]:
            out[f["key"]] = f
    return out


def selected_provider(db: Session, capability: str) -> str:
    return get_setting(db, SELECTOR_KEY[capability]) or DEFAULT_PROVIDER[capability]


def _provider_configured(db: Session, capability: str, provider: str) -> bool:
    """True when every required (non-optional) credential for a provider is set.
    The UI keys ``configured`` by provider, not by field."""
    meta = CATALOGS[capability].get(provider)
    if not meta:
        return False
    required = [f for f in meta["credential_fields"] if "optional" not in f["label"].lower()]
    return bool(required) and all(get_setting(db, f["key"]) for f in required)


def catalog_for_api(db: Session, capability: str) -> dict:
    """Response shape is the app's ProviderCatalog, verbatim, so the ported
    ServiceProviders component runs unmodified against the control plane."""
    cat = CATALOGS[capability]
    current = selected_provider(db, capability)
    current_model = get_setting(db, MODEL_KEY) or cat.get(current, {}).get("default_model")

    providers = []
    for key, meta in cat.items():
        info = {"provider": key, **meta}
        if capability == "ai":
            info["models_source"] = "curated"
            info["models_fetched_at"] = None
        providers.append(info)

    model_ids = {m["id"] for m in cat.get(current, {}).get("models", [])}
    return {
        "current_provider": current,
        "default_provider": DEFAULT_PROVIDER[capability],
        "current_model": current_model if capability == "ai" else None,
        "current_model_available": (current_model in model_ids) if (capability == "ai" and model_ids) else True,
        "configured": {k: _provider_configured(db, capability, k) for k in cat},
        "providers": providers,
    }


def save_provider(db: Session, capability: str, provider: str, model: str | None, settings: dict) -> str:
    """Select a provider for a capability and save its settings/secrets.
    Blank values are ignored (existing secret kept). Ported from the app's
    save_provider, including its validation — a bad key or model is rejected,
    never silently dropped.
    """
    cat = CATALOGS[capability]
    provider_id = (provider or "").strip().lower()
    if provider_id not in cat:
        raise ValueError(f"Unknown {capability} provider: {provider}")

    # Only the credential keys this provider's catalog declares may be written
    # through this endpoint — it must not become an arbitrary secret writer.
    allowed_keys = {f["key"] for f in cat[provider_id].get("credential_fields", [])}
    unknown = [k for k in (settings or {}) if k not in allowed_keys]
    if unknown:
        raise ValueError(f"Unexpected settings for {provider_id}: {', '.join(sorted(unknown))}")

    if capability == "ai" and model:
        allowed_models = {m["id"] for m in cat[provider_id].get("models", [])}
        if allowed_models and model not in allowed_models:
            raise ValueError(f"Unknown model for {provider_id}: {model}")

    set_setting(db, SELECTOR_KEY[capability], provider_id)
    if capability == "ai" and model:
        set_setting(db, MODEL_KEY, model)
    fields = {f["key"]: f for f in cat[provider_id]["credential_fields"]}
    for key, value in (settings or {}).items():
        if value and str(value).strip():  # blank = keep existing
            set_setting(db, key, str(value).strip(), is_secret=bool(fields[key].get("secret")))
    return provider_id


def provider_status(db: Session, capability: str) -> dict:
    """Connectivity check for the currently-configured provider — the app's
    test_provider, ported. Returns {ok, detail}.

    Identity is a genuine live check: OIDC discovery is plain HTTP and the panel
    already speaks it, so this hits the issuer exactly as the app does. AI and
    translation are verified as *configured* rather than called: the control
    plane deliberately doesn't carry the Vertex/Bedrock/Azure SDKs (it brokers
    credentials for towns, it doesn't run inference), so there is no adapter to
    call. The detail text says which of the two happened, so an operator is
    never told a key "works" when it was only present.
    """
    provider = selected_provider(db, capability)
    meta = CATALOGS[capability].get(provider)
    if not meta:
        return {"ok": False, "detail": f"No {capability} provider is configured."}

    missing = [
        f["label"] for f in meta["credential_fields"]
        if "optional" not in f["label"].lower() and not get_setting(db, f["key"])
    ]
    if missing:
        return {
            "ok": False,
            "detail": f"No {capability} provider is fully configured — missing: {', '.join(missing)}. "
                      "Enter the required fields and save first.",
        }

    if capability == "identity":
        # Live discovery, mirroring the app's identity test.
        issuer = (
            get_setting(db, "OIDC_ISSUER")
            or get_setting(db, "OKTA_ISSUER")
            or (f"https://{get_setting(db, 'AUTH0_DOMAIN')}" if get_setting(db, "AUTH0_DOMAIN") else None)
            or (
                f"{(get_setting(db, 'ENTRA_AUTHORITY') or 'https://login.microsoftonline.com').rstrip('/')}"
                f"/{get_setting(db, 'ENTRA_TENANT_ID')}/v2.0"
                if get_setting(db, "ENTRA_TENANT_ID") else None
            )
        )
        if not issuer:
            return {"ok": False, "detail": "No issuer configured for the selected identity provider."}
        try:
            from orchestrator import oidc

            meta_doc = oidc.discover(issuer)
            ok = bool(meta_doc.get("authorization_endpoint"))
            return {
                "ok": ok,
                "detail": f"Discovered {provider} endpoints at {issuer}" if ok
                          else f"No authorization endpoint in the discovery document at {issuer}",
            }
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "detail": f"Test failed: {str(e)[:200]}"}

    return {
        "ok": True,
        "detail": f"{meta['name']} is configured (credentials stored). The control plane "
                  "brokers these credentials to towns; it does not call the provider itself.",
    }


def derive_cloud_profile(ai: str, translation: str, secrets: str, kms: str | None = None) -> str:
    """Report which named profile the current core selections match, or 'mixed'.
    Matches on the boundary-defining set (AI, translation, secret store, and KMS
    when provided); email/SMS can legitimately differ and aren't part of the match.

    Ported from the app's _derive_cloud_profile.
    """
    for pid, p in CLOUD_PROFILES.items():
        if ai == p["ai"] and translation == p["translation"] and secrets == p["secrets"]:
            if kms is not None and kms != p["kms"]:
                continue
            return pid
    return "mixed"


def _kms_provider_safe() -> str:
    from orchestrator.encryption import _kms_provider

    try:
        return _kms_provider()
    except Exception:  # noqa: BLE001 — never let a config probe break the page
        return "google"


def cloud_profile_state(db: Session) -> dict:
    """Current cloud environment — the app's get_cloud_profile, ported."""
    ai = selected_provider(db, "ai")
    translation = selected_provider(db, "translation")
    identity = selected_provider(db, "identity")
    email = get_setting(db, "EMAIL_PROVIDER") or "smtp"
    sms = get_setting(db, "SMS_PROVIDER") or ""
    secrets = secrets_provider()
    kms = _kms_provider_safe()
    return {
        "profile": derive_cloud_profile(ai, translation, secrets, kms),
        # The app locks this in managed (state-hosted) mode. The control plane
        # *is* the state's hosting platform, so it is never managed from above.
        "managed": False,
        "components": {
            "ai": ai, "translation": translation, "secrets": secrets, "kms": kms,
            "identity": identity, "email": email, "sms": sms,
        },
        "maps": {"provider": "google", "locked": True, "label": "Google Maps (required)"},
        "profiles": [{"id": k, **v} for k, v in CLOUD_PROFILES.items()],
    }


def apply_cloud_profile(db: Session, profile_id: str, apply_identity: bool = False) -> dict:
    """Apply a whole cloud environment in one choice — the app's set_cloud_profile.

    Sets AI, translation, the secret store and KMS together, because those four
    are what define the compliance boundary. Email/SMS are only written when the
    cloud has a native option (Google has no first-party SMS, so an existing
    Twilio selection survives a switch to the Google profile).
    """
    pid = (profile_id or "").strip().lower()
    if pid not in CLOUD_PROFILES:
        raise ValueError(f"Unknown cloud profile: {profile_id}")
    p = CLOUD_PROFILES[pid]

    set_setting(db, SELECTOR_KEY["ai"], p["ai"])
    set_setting(db, SELECTOR_KEY["translation"], p["translation"])
    set_setting(db, "SECRETS_PROVIDER", p["secrets"])
    set_setting(db, "KMS_PROVIDER", p["kms"])
    if p.get("email"):
        set_setting(db, "EMAIL_PROVIDER", p["email"])
    if p.get("sms"):
        set_setting(db, "SMS_PROVIDER", p["sms"])

    identity_applied = False
    if apply_identity and p.get("identity_recommended"):
        set_setting(db, SELECTOR_KEY["identity"], p["identity_recommended"])
        identity_applied = True

    warnings: list[str] = []
    # Gov-readiness: flipping the secret store to a vault that isn't wired up yet
    # is allowed (writes fall back to the encrypted DB), but say so plainly.
    import os

    if p["secrets"] == "azure":
        if not (os.getenv("AZURE_KEY_VAULT_URL") or os.getenv("AZURE_KEYVAULT_URL")):
            warnings.append(
                "Azure Key Vault isn't configured yet — secrets stay in the encrypted "
                "database until Key Vault credentials are added."
            )
    elif p["secrets"] == "google":
        from orchestrator.encryption import _is_kms_available

        try:
            if not _is_kms_available():
                warnings.append(
                    "Google Secret Manager isn't reachable yet — secrets stay in the "
                    "encrypted database until GOOGLE_CLOUD_PROJECT and credentials are set."
                )
        except Exception:  # noqa: BLE001
            pass
    elif p["secrets"] == "aws":
        if not os.getenv("AWS_REGION"):
            warnings.append(
                "AWS Secrets Manager isn't configured yet (set AWS_REGION + credentials) — "
                "secrets stay in the encrypted database until then."
            )

    # Control-plane addition: the boundary is only real once the newly selected
    # providers actually have credentials, so name the ones still missing.
    for cap in ("ai", "translation"):
        prov = p[cap]
        if not _provider_configured(db, cap, prov):
            warnings.append(
                f"{CATALOGS[cap][prov]['name']} has no credentials yet — add them below before it can be used."
            )

    return {
        "ok": True,
        "profile": pid,
        "components": {
            "ai": p["ai"], "translation": p["translation"], "secrets": p["secrets"],
            "kms": p["kms"], "email": p["email"], "sms": p["sms"],
        },
        "identity_recommended": p.get("identity_recommended", ""),
        "identity_applied": identity_applied,
        "warnings": warnings,
    }
