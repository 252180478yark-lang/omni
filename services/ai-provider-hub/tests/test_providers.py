from fastapi.testclient import TestClient

from app.main import app
from app.runtime import bootstrap_providers, registry


def test_health_and_provider_listing(monkeypatch) -> None:
    monkeypatch.setenv("OMNI_BUILD_COMMIT", "baked-commit")
    monkeypatch.setenv("OMNI_BUILD_SOURCE_FINGERPRINT", "sha256:baked")
    monkeypatch.setenv("OMNI_SOURCE_FINGERPRINT", "sha256:runtime-expected")
    bootstrap_providers()
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["service"] == "ai-provider-hub"
    assert health.json()["build_commit"] == "baked-commit"
    assert health.json()["build_source_fingerprint"] == "sha256:baked"
    assert "runtime-expected" not in str(health.json())

    providers = client.get("/api/v1/ai/providers")
    assert providers.status_code == 200
    provider_data = providers.json()["providers"]
    assert "gemini" in provider_data
    assert "openai" in provider_data
    assert "ollama" in provider_data

    models = client.get("/api/v1/ai/models")
    assert models.status_code == 200
    assert isinstance(models.json()["models"], list)


def test_openai_compat_chat_completion_mock() -> None:
    bootstrap_providers()
    assert registry.list_providers()
    client = TestClient(app)

    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": False,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["object"] == "chat.completion"
    assert payload["choices"][0]["message"]["content"]
