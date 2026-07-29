"""Cloud service providers (AI / translation / identity) + cloud profiles.

The response shapes are the app's provider contract verbatim, so the ported
ServiceProviders component runs against the control plane unmodified — these
tests pin that contract.
"""

from tests.conftest import HEADERS


def test_catalog_matches_app_contract(client):
    c = client.get("/api/providers/ai/catalog", headers=HEADERS).json()
    # App's ProviderCatalog keys.
    assert c["current_provider"] == "vertex"
    assert c["default_provider"] == "vertex"
    assert c["current_model"] and c["current_model_available"] is True
    assert {p["provider"] for p in c["providers"]} == {"vertex", "azure", "bedrock"}
    # configured is keyed by PROVIDER (the UI does configured[selected]).
    assert set(c["configured"]) == {"vertex", "azure", "bedrock"}
    assert all(v is False for v in c["configured"].values())
    # AI providers carry model discovery metadata.
    assert c["providers"][0]["models_source"] == "curated"


def test_save_provider_marks_it_configured(client):
    r = client.post(
        "/api/providers/ai/save",
        json={"provider": "azure", "model": "gpt-4o", "settings": {
            "AZURE_OPENAI_ENDPOINT": "https://x.openai.azure.us",
            "AZURE_OPENAI_API_KEY": "supersecret",
            "AZURE_OPENAI_DEPLOYMENT": "gpt4o",
        }},
        headers=HEADERS,
    )
    assert r.status_code == 200 and r.json() == {"ok": True, "provider": "azure"}

    c = client.get("/api/providers/ai/catalog", headers=HEADERS).json()
    assert c["current_provider"] == "azure" and c["current_model"] == "gpt-4o"
    assert c["configured"]["azure"] is True and c["configured"]["vertex"] is False
    # Secrets are never returned anywhere in the catalog payload.
    assert "supersecret" not in r.text and "supersecret" not in str(c)

    t = client.post("/api/providers/ai/test", headers=HEADERS).json()
    assert t["ok"] is True and "detail" in t  # app shape is {ok, detail}


def test_models_refresh_shape(client):
    r = client.post("/api/providers/ai/models/refresh", json={"provider": "bedrock"}, headers=HEADERS).json()
    assert r["provider"] == "bedrock" and r["source"] == "curated"
    assert r["models"] and {"id", "label"} <= set(r["models"][0])


def test_unknown_provider_rejected(client):
    # 400, matching the app's save_provider.
    assert client.post("/api/providers/ai/save", json={"provider": "skynet", "settings": {}},
                       headers=HEADERS).status_code == 400
    assert client.post("/api/providers/ai/models/refresh", json={"provider": "skynet"},
                       headers=HEADERS).status_code == 422


def test_save_is_not_an_arbitrary_secret_writer(client):
    """The app rejects credential keys a provider's catalog doesn't declare, so
    this endpoint can't be used to write any secret it likes. Ported behaviour:
    reject loudly rather than silently dropping the key."""
    r = client.post(
        "/api/providers/ai/save",
        json={"provider": "vertex", "settings": {"PANEL_API_TOKEN": "pwned"}},
        headers=HEADERS,
    )
    assert r.status_code == 400 and "Unexpected settings" in r.json()["detail"]


def test_save_rejects_a_model_the_provider_does_not_offer(client):
    r = client.post(
        "/api/providers/ai/save",
        json={"provider": "vertex", "model": "gpt-4o", "settings": {}},
        headers=HEADERS,
    )
    assert r.status_code == 400 and "Unknown model" in r.json()["detail"]


def test_blank_value_keeps_the_existing_secret(client):
    client.post("/api/providers/ai/save", json={"provider": "azure", "settings": {
        "AZURE_OPENAI_ENDPOINT": "https://first.openai.azure.us",
        "AZURE_OPENAI_API_KEY": "first-key",
        "AZURE_OPENAI_DEPLOYMENT": "d",
    }}, headers=HEADERS)
    # Re-save with a blank key — the stored secret must survive.
    client.post("/api/providers/ai/save", json={"provider": "azure", "settings": {
        "AZURE_OPENAI_ENDPOINT": "https://second.openai.azure.us",
        "AZURE_OPENAI_API_KEY": "",
    }}, headers=HEADERS)
    c = client.get("/api/providers/ai/catalog", headers=HEADERS).json()
    assert c["configured"]["azure"] is True  # key still present, not wiped


def test_cloud_profile_state_matches_app_contract(client):
    st = client.get("/api/providers/cloud-profile", headers=HEADERS).json()
    assert st["profile"] == "google"  # defaults are vertex + google
    assert st["managed"] is False
    assert set(st["components"]) == {"ai", "translation", "identity", "secrets", "kms", "email", "sms"}
    assert st["maps"]["locked"] is True
    assert {p["id"] for p in st["profiles"]} == {"google", "azure", "aws"}


def test_apply_cloud_profile_switches_the_whole_boundary(client):
    r = client.post("/api/providers/cloud-profile", json={"profile": "aws", "apply_identity": True},
                    headers=HEADERS).json()
    assert r["ok"] is True and r["profile"] == "aws" and r["identity_applied"] is True
    # The boundary-defining set moves together — not just AI/translation.
    assert r["components"] == {"ai": "bedrock", "translation": "aws", "secrets": "aws",
                               "kms": "aws", "email": "ses", "sms": "sns"}
    assert r["identity_recommended"] == "oidc"
    # Switching to a boundary with no credentials entered warns rather than
    # silently leaving the fleet pointed at an unusable provider.
    assert any("credentials" in w for w in r["warnings"])

    # And it actually takes effect: the persisted SECRETS_PROVIDER/KMS_PROVIDER
    # are read back, so the state derives 'aws' rather than falling to 'mixed'.
    st = client.get("/api/providers/cloud-profile", headers=HEADERS).json()
    assert st["profile"] == "aws"
    assert st["components"]["secrets"] == "aws" and st["components"]["kms"] == "aws"
    assert st["components"]["identity"] == "oidc"


def test_google_profile_leaves_sms_alone(client):
    """Google has no first-party SMS, so an existing SMS choice must survive."""
    client.post("/api/providers/cloud-profile", json={"profile": "aws"}, headers=HEADERS)
    client.post("/api/providers/cloud-profile", json={"profile": "google"}, headers=HEADERS)
    st = client.get("/api/providers/cloud-profile", headers=HEADERS).json()
    assert st["components"]["email"] == "smtp"
    assert st["components"]["sms"] == "sns"  # not clobbered by the google profile


def test_mixed_profile_when_selections_do_not_match_a_cloud(client):
    # Matching is on the boundary set (ai + translation + secrets [+ kms]), so a
    # half-switched configuration reports 'mixed' rather than a false match.
    client.post("/api/providers/ai/save", json={"provider": "bedrock", "settings": {}}, headers=HEADERS)
    client.post("/api/providers/translation/save", json={"provider": "azure", "settings": {}}, headers=HEADERS)
    st = client.get("/api/providers/cloud-profile", headers=HEADERS).json()
    assert st["profile"] == "mixed"


def test_unknown_capability_404(client):
    assert client.get("/api/providers/nonsense/catalog", headers=HEADERS).status_code == 404
