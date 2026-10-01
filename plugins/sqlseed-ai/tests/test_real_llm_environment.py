"""Selected live backends must not inherit another service's URL or credentials."""

from __future__ import annotations

import pytest

from tests._helpers import configure_llm_backend_env

try:
    from sqlseed_ai.config import AIConfig
except ModuleNotFoundError as exc:
    if exc.name != "sqlseed_ai":
        raise
    pytest.skip("sqlseed-ai plugin not installed", allow_module_level=True)


@pytest.mark.parametrize(
    ("backend", "expected_url", "expected_key"),
    [
        ("ollama", "http://localhost:11434/v1", "ollama"),
        ("lm_studio", "http://localhost:1234/v1", "lm-studio"),
        ("google_ai_studio", "https://generativelanguage.googleapis.com/v1beta/openai/", "google-test-key"),
    ],
)
def test_live_backend_configuration_is_service_scoped(
    monkeypatch: pytest.MonkeyPatch, backend: str, expected_url: str, expected_key: str
) -> None:
    """Isolate selected-service credentials, endpoint and protocol from unrelated environment values."""
    for variable, value in {
        "SQLSEED_AI_API_KEY": "other-service-key",
        "OPENAI_API_KEY": "other-fallback-key",
        "GOOGLE_API_KEY": "google-test-key",
        "SQLSEED_AI_BASE_URL": "https://unrelated.invalid/v1",
        "OPENAI_BASE_URL": "https://another.invalid/v1",
        "SQLSEED_AI_TOOL_CALLING_PROTOCOL": "none",
        "SQLSEED_AI_TIMEOUT": "invalid-timeout",
    }.items():
        monkeypatch.setenv(variable, value)

    configure_llm_backend_env(monkeypatch, backend, "selected-model")

    config = AIConfig.from_env()
    assert config.backend.value == backend
    assert config.resolve_base_url().rstrip("/") == expected_url.rstrip("/")
    assert config.resolve_api_key() == expected_key
    assert config.model == "selected-model"
    assert config.tool_calling_protocol == "gemma4"


def test_google_acceptance_does_not_borrow_another_service_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Leave missing Google credentials unset rather than reusing another provider's key."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("SQLSEED_AI_API_KEY", "other-service-key")
    monkeypatch.setenv("OPENAI_API_KEY", "other-fallback-key")

    configure_llm_backend_env(monkeypatch, "google_ai_studio", "selected-model")

    assert AIConfig.from_env().resolve_api_key() is None
