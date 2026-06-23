"""Tests for untested methods of :class:`sqlseed_ai.config.AIConfig`.

Covers ``resolve_base_url``, ``resolve_api_key``, ``has_real_api_key``,
``is_small_local_model``, ``is_reasoning_model``, ``should_use_streaming``,
``should_use_ultra_compact``, and ``apply_overrides``. All environment
variable access is isolated via ``monkeypatch`` so tests do not depend on
the host's real environment.
"""

from __future__ import annotations

import pytest

try:
    from sqlseed_ai.config import (
        GOOGLE_AI_STUDIO_BASE_URL,
        LM_STUDIO_BASE_URL,
        OLLAMA_BASE_URL,
        AIBackend,
        AIConfig,
    )
except ImportError:
    pytest.skip("sqlseed-ai plugin not installed", allow_module_level=True)


class TestResolveBaseUrl:
    """Tests for :meth:`AIConfig.resolve_base_url`."""

    def test_resolve_base_url_google_ai_studio(self) -> None:
        """Verify resolve_base_url() returns Google AI Studio URL for google_ai_studio backend."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO)
        assert config.resolve_base_url() == GOOGLE_AI_STUDIO_BASE_URL

    def test_resolve_base_url_lm_studio(self) -> None:
        """Verify resolve_base_url() returns LM Studio URL for lm_studio backend."""
        config = AIConfig(backend=AIBackend.LM_STUDIO)
        assert config.resolve_base_url() == LM_STUDIO_BASE_URL

    def test_resolve_base_url_ollama(self) -> None:
        """Verify resolve_base_url() returns Ollama URL for ollama backend."""
        config = AIConfig(backend=AIBackend.OLLAMA)
        assert config.resolve_base_url() == OLLAMA_BASE_URL

    def test_resolve_base_url_openai_compat_with_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify resolve_base_url() uses self.base_url for openai_compat backend.

        OPENAI_COMPAT requires an explicit base_url (no built-in default).
        """
        custom_url = "https://openrouter.ai/api/v1"
        config = AIConfig(backend=AIBackend.OPENAI_COMPAT, base_url=custom_url)
        assert config.resolve_base_url() == custom_url

    def test_resolve_base_url_user_override(self) -> None:
        """Verify user-provided base_url takes precedence over backend default."""
        custom_url = "https://custom.example.com/v1"
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, base_url=custom_url)
        assert config.resolve_base_url() == custom_url

    def test_resolve_base_url_openai_compat_raises_without_url(self) -> None:
        """Verify resolve_base_url() raises ValueError for openai_compat without base_url."""
        config = AIConfig(backend=AIBackend.OPENAI_COMPAT, base_url=None)
        with pytest.raises(ValueError, match="OPENAI_COMPAT backend requires"):
            config.resolve_base_url()


class TestResolveApiKey:
    """Tests for :meth:`AIConfig.resolve_api_key`."""

    def test_resolve_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify resolve_api_key() reads SQLSEED_AI_API_KEY when no explicit key set."""
        monkeypatch.setenv("SQLSEED_AI_API_KEY", "sk-from-env")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, api_key=None)
        assert config.resolve_api_key() == "sk-from-env"

    def test_resolve_api_key_fallback_openai(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify resolve_api_key() falls back to OPENAI_API_KEY when SQLSEED_AI_API_KEY unset."""
        monkeypatch.delenv("SQLSEED_AI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-fallback")
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, api_key=None)
        assert config.resolve_api_key() == "sk-openai-fallback"

    def test_resolve_api_key_local_placeholder(self) -> None:
        """Verify resolve_api_key() returns placeholder for local backends without a key."""
        lm_config = AIConfig(backend=AIBackend.LM_STUDIO, api_key=None)
        assert lm_config.resolve_api_key() == "lm-studio"
        ollama_config = AIConfig(backend=AIBackend.OLLAMA, api_key=None)
        assert ollama_config.resolve_api_key() == "ollama"

    def test_resolve_api_key_explicit_takes_precedence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify explicit api_key takes precedence over environment variables."""
        monkeypatch.setenv("SQLSEED_AI_API_KEY", "sk-env")
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, api_key="sk-explicit")
        assert config.resolve_api_key() == "sk-explicit"


class TestHasRealApiKey:
    """Tests for :attr:`AIConfig.has_real_api_key`."""

    def test_has_real_api_key_true(self) -> None:
        """Verify has_real_api_key returns True when a real key is set on cloud backend."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, api_key="sk-real-key")
        assert config.has_real_api_key is True

    def test_has_real_api_key_false_for_local_backend(self) -> None:
        """Verify has_real_api_key returns False for local backends (placeholder keys)."""
        lm_config = AIConfig(backend=AIBackend.LM_STUDIO, api_key="lm-studio")
        assert lm_config.has_real_api_key is False
        ollama_config = AIConfig(backend=AIBackend.OLLAMA, api_key="ollama")
        assert ollama_config.has_real_api_key is False

    def test_has_real_api_key_false_when_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify has_real_api_key returns False when no key is set and env vars are empty."""
        monkeypatch.delenv("SQLSEED_AI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, api_key=None)
        assert config.has_real_api_key is False

    def test_has_real_api_key_true_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify has_real_api_key returns True when key is available via env var."""
        monkeypatch.setenv("SQLSEED_AI_API_KEY", "sk-env-key")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, api_key=None)
        assert config.has_real_api_key is True


class TestSmallLocalAndReasoningModels:
    """Tests for :meth:`is_small_local_model` and :meth:`is_reasoning_model`."""

    def test_is_small_local_model_true_for_e4b(self) -> None:
        """Verify is_small_local_model() returns True for E4B on local backend."""
        config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-e4b")
        assert config.is_small_local_model() is True

    def test_is_small_local_model_true_for_e2b(self) -> None:
        """Verify is_small_local_model() returns True for E2B on local backend."""
        config = AIConfig(backend=AIBackend.OLLAMA, model="gemma4:e2b")
        assert config.is_small_local_model() is True

    def test_is_small_local_model_false_for_26b(self) -> None:
        """Verify is_small_local_model() returns False for 26B model on local backend."""
        config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-26b-a4b")
        assert config.is_small_local_model() is False

    def test_is_small_local_model_false_for_cloud_backend(self) -> None:
        """Verify is_small_local_model() returns False for E4B on cloud backend."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-e4b-it")
        assert config.is_small_local_model() is False

    def test_is_reasoning_model_true_for_e2b(self) -> None:
        """Verify is_reasoning_model() returns True for E2B model IDs."""
        config = AIConfig(model="gemma-4-e2b-it")
        assert config.is_reasoning_model() is True

    def test_is_reasoning_model_true_for_e4b_lm_studio_format(self) -> None:
        """Verify is_reasoning_model() returns True for LM Studio E4B model ID."""
        config = AIConfig(model="google/gemma-4-e4b")
        assert config.is_reasoning_model() is True

    def test_is_reasoning_model_false_for_26b(self) -> None:
        """Verify is_reasoning_model() returns False for 26B model."""
        config = AIConfig(model="gemma-4-26b-a4b-it")
        assert config.is_reasoning_model() is False

    def test_is_reasoning_model_false_for_31b(self) -> None:
        """Verify is_reasoning_model() returns False for 31B model."""
        config = AIConfig(model="gemma-4-31b-it")
        assert config.is_reasoning_model() is False

    def test_is_reasoning_model_false_for_none(self) -> None:
        """Verify is_reasoning_model() returns False when model is None."""
        config = AIConfig(model=None)
        assert config.is_reasoning_model() is False


class TestStreamingAndUltraCompact:
    """Tests for :meth:`should_use_streaming` and :meth:`should_use_ultra_compact`."""

    def test_should_use_streaming_large_model(self) -> None:
        """Verify should_use_streaming() returns True for large models (non-small-local)."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        assert config.should_use_streaming() is True

    def test_should_use_streaming_false_for_small_local(self) -> None:
        """Verify should_use_streaming() returns False for small local models."""
        config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-e4b")
        assert config.should_use_streaming() is False

    def test_should_use_streaming_true_for_local_large_model(self) -> None:
        """Verify should_use_streaming() returns True for 12B+ local models."""
        config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-12b")
        assert config.should_use_streaming() is True

    def test_should_use_ultra_compact_true_for_small_local(self) -> None:
        """Verify should_use_ultra_compact() returns True for small local models.

        Small local models benefit from ultra-compact prompts to reduce
        prompt tokens and prefill time (TTFT).
        """
        config = AIConfig(backend=AIBackend.OLLAMA, model="gemma4:e4b")
        assert config.should_use_ultra_compact() is True

    def test_should_use_ultra_compact_false_for_large_model(self) -> None:
        """Verify should_use_ultra_compact() returns False for large/cloud models."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        assert config.should_use_ultra_compact() is False


class TestApplyOverrides:
    """Tests for :meth:`AIConfig.apply_overrides`."""

    def test_apply_overrides_sets_values(self) -> None:
        """Verify apply_overrides() updates config fields and returns self for chaining."""
        config = AIConfig()
        result = config.apply_overrides(
            api_key="sk-new",
            base_url="https://new.example.com/v1",
            model="gemma-4-31b-it",
            backend=AIBackend.OLLAMA,
        )
        assert result is config  # Returns self for chaining
        assert config.api_key == "sk-new"
        assert config.base_url == "https://new.example.com/v1"
        assert config.model == "gemma-4-31b-it"
        assert config.backend == AIBackend.OLLAMA

    def test_apply_overrides_skips_none_values(self) -> None:
        """Verify apply_overrides() does not overwrite fields with None."""
        config = AIConfig(
            api_key="sk-original",
            model="gemma-4-26b-a4b-it",
            backend=AIBackend.GOOGLE_AI_STUDIO,
        )
        config.apply_overrides(api_key=None, model=None, backend=None)
        # None values should not overwrite existing fields
        assert config.api_key == "sk-original"
        assert config.model == "gemma-4-26b-a4b-it"
        assert config.backend == AIBackend.GOOGLE_AI_STUDIO

    def test_apply_overrides_partial_update(self) -> None:
        """Verify apply_overrides() can update a single field without touching others."""
        config = AIConfig(api_key="sk-keep", model="gemma-4-26b-a4b-it")
        config.apply_overrides(model="gemma-4-e4b-it")
        assert config.api_key == "sk-keep"  # Unchanged
        assert config.model == "gemma-4-e4b-it"  # Updated
