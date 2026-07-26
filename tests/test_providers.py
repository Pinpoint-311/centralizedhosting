"""Cloud service providers (AI / translation / identity) + cloud profiles."""

from tests.conftest import HEADERS


def test_catalog_defaults(client):
    c = client.get("/api/providers/ai/catalog", headers=HEADERS).json()
    assert c["selected"] == "vertex"
    assert {p["provider"] for p in c["providers"]} == {"vertex", "azure", "bedrock"}
    assert c["model"]  # default model present


def test_save_provider_persists_and_hides_secrets(client):
    r = client.post(
        "/api/providers/ai/save",
        json={"provider": "azure", "model": "gpt-4o", "credentials": {
            "AZURE_OPENAI_ENDPOINT": "https://x.openai.azure.us",
            "AZURE_OPENAI_API_KEY": "supersecret",
            "AZURE_OPENAI_DEPLOYMENT": "gpt4o",
        }},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["selected"] == "azure" and out["model"] == "gpt-4o"
    # Non-secret values echoed; the secret API key is never returned.
    assert out["values"].get("AZURE_OPENAI_ENDPOINT") == "https://x.openai.azure.us"
    assert "AZURE_OPENAI_API_KEY" not in out["values"]
    assert out["configured"].get("AZURE_OPENAI_API_KEY") is True
    # And the light 'test' passes now that required creds are present.
    assert client.post("/api/providers/ai/test", headers=HEADERS).json()["ok"] is True


def test_unknown_provider_rejected(client):
    r = client.post("/api/providers/ai/save", json={"provider": "skynet", "credentials": {}}, headers=HEADERS)
    assert r.status_code == 422


def test_cloud_profile_apply_sets_ai_and_translation(client):
    st = client.post("/api/providers/cloud-profile", json={"profile": "aws", "apply_identity": True}, headers=HEADERS).json()
    assert st["current"] == "aws"
    assert st["components"] == {"ai": "bedrock", "translation": "aws", "identity": "oidc"}


def test_unknown_capability_404(client):
    assert client.get("/api/providers/nonsense/catalog", headers=HEADERS).status_code == 404
