"""Tests for the Gemma 4 model selection and fallback logic.

Covers :func:`_normalize_model_id` (cross-platform model ID comparison),
:func:`select_gemma_model` (default model per backend), and
:func:`select_next_gemma_model` (graceful fallback to smaller variants).
"""

from __future__ import annotations

import pytest

try:
    from sqlseed_ai._model_selector import (
        _normalize_model_id,
        select_gemma_model,
        select_next_gemma_model,
    )
    from sqlseed_ai.config import AIBackend
except ImportError:
    pytest.skip("sqlseed-ai plugin not installed", allow_module_level=True)


class TestNormalizeModelId:
    """Tests for :func:`_normalize_model_id`."""

    def test_normalize_model_id_strips_provider_prefix(self) -> None:
        """Verify _normalize_model_id() strips the 'google/' provider prefix."""
        # LM Studio format: "google/gemma-4-e4b" -> "gemma-4-e4b"
        assert _normalize_model_id("google/gemma-4-e4b") == "gemma-4-e4b"
        # OpenRouter format: "google/gemma-4-e4b-it" -> "gemma-4-e4b"
        assert _normalize_model_id("google/gemma-4-e4b-it") == "gemma-4-e4b"
        # OpenRouter free tier: "google/gemma-4-26b-a4b-it:free" -> "gemma-4-26b-a4b"
        assert _normalize_model_id("google/gemma-4-26b-a4b-it:free") == "gemma-4-26b-a4b"

    def test_normalize_model_id_strips_it_suffix(self) -> None:
        """Verify _normalize_model_id() strips the '-it' instruction-tuned suffix."""
        # Google AI Studio format: "gemma-4-e4b-it" -> "gemma-4-e4b"
        assert _normalize_model_id("gemma-4-e4b-it") == "gemma-4-e4b"
        assert _normalize_model_id("gemma-4-26b-a4b-it") == "gemma-4-26b-a4b"
        assert _normalize_model_id("gemma-4-31b-it") == "gemma-4-31b"

    def test_normalize_model_id_lowercase(self) -> None:
        """Verify _normalize_model_id() lowercases the model ID."""
        assert _normalize_model_id("GEMMA-4-E4B-IT") == "gemma-4-e4b"
        assert _normalize_model_id("Google/Gemma-4-26B-A4B-IT") == "gemma-4-26b-a4b"

    def test_normalize_model_id_ollama_format(self) -> None:
        """Verify _normalize_model_id() converts Ollama 'gemma4:xxb' format."""
        # Ollama format: "gemma4:e4b" -> "gemma-4-e4b"
        assert _normalize_model_id("gemma4:e4b") == "gemma-4-e4b"
        assert _normalize_model_id("gemma4:26b") == "gemma-4-26b"
        assert _normalize_model_id("gemma4:12b") == "gemma-4-12b"

    def test_normalize_model_id_handles_empty_string(self) -> None:
        """Verify _normalize_model_id() handles empty string gracefully."""
        assert _normalize_model_id("") == ""


class TestSelectGemmaModel:
    """Tests for :func:`select_gemma_model`."""

    def test_select_gemma_model_google_ai_studio(self) -> None:
        """Verify select_gemma_model() returns 26B for google_ai_studio backend.

        Google AI Studio defaults to the recommended 26B A4B MoE model.
        """
        result = select_gemma_model(backend=AIBackend.GOOGLE_AI_STUDIO)
        # Google AI Studio uses canonical format: gemma-4-26b-a4b-it
        assert result == "gemma-4-26b-a4b-it"

    def test_select_gemma_model_openai_compat(self) -> None:
        """Verify select_gemma_model() returns 26B for openai_compat backend."""
        result = select_gemma_model(backend=AIBackend.OPENAI_COMPAT)
        # OpenAI-compatible (e.g., OpenRouter) uses google/ prefix
        assert result == "google/gemma-4-26b-a4b-it"

    def test_select_gemma_model_local_prefer_small(self) -> None:
        """Verify select_gemma_model() returns E4B when prefer_small=True.

        prefer_small forces the compact E4B model regardless of backend,
        useful for edge/local inference.
        """
        result = select_gemma_model(backend=AIBackend.GOOGLE_AI_STUDIO, prefer_small=True)
        assert result == "gemma-4-e4b-it"

    def test_select_gemma_model_lm_studio_defaults_to_small(self) -> None:
        """Verify select_gemma_model() returns E4B for LM Studio (local default)."""
        result = select_gemma_model(backend=AIBackend.LM_STUDIO)
        # LM Studio uses google/ prefix without -it suffix
        assert result == "google/gemma-4-e4b"

    def test_select_gemma_model_ollama_defaults_to_small(self) -> None:
        """Verify select_gemma_model() returns E4B for Ollama (local default)."""
        result = select_gemma_model(backend=AIBackend.OLLAMA)
        # Ollama uses gemma4:xxb format
        assert result == "gemma4:e4b"


class TestSelectNextGemmaModel:
    """Tests for :func:`select_next_gemma_model`."""

    def test_select_next_gemma_model_returns_fallback(self) -> None:
        """Verify select_next_gemma_model() returns the next smaller model in the chain.

        Priority order: 26B > 31B > 12B > E4B > E2B.
        After 26B fails, the next available model is 31B.
        """
        result = select_next_gemma_model(failed_model="gemma-4-26b-a4b-it", backend=AIBackend.GOOGLE_AI_STUDIO)
        # 31B is next in priority after 26B
        assert result == "gemma-4-31b-it"

    def test_select_next_gemma_model_skips_local_only_for_cloud(self) -> None:
        """Verify select_next_gemma_model() skips 12B (local-only) for cloud backends.

        Gemma 4 12B is not available on Google AI Studio, so after 31B
        fails the next model should be E4B (skipping 12B).
        """
        result = select_next_gemma_model(failed_model="gemma-4-31b-it", backend=AIBackend.GOOGLE_AI_STUDIO)
        # 12B is local-only, so skip to E4B
        assert result == "gemma-4-e4b-it"

    def test_select_next_gemma_model_includes_12b_for_local(self) -> None:
        """Verify select_next_gemma_model() includes 12B for local backends."""
        result = select_next_gemma_model(failed_model="gemma-4-31b-it", backend=AIBackend.LM_STUDIO)
        # 12B is available on local backends
        assert result == "google/gemma-4-12b"

    def test_select_next_gemma_model_returns_none_when_exhausted(self) -> None:
        """Verify select_next_gemma_model() returns None when all models exhausted.

        E2B is the smallest model; no fallback exists after it.
        """
        result = select_next_gemma_model(failed_model="gemma-4-e2b-it", backend=AIBackend.GOOGLE_AI_STUDIO)
        assert result is None

    def test_select_next_gemma_model_returns_none_for_unknown_model(self) -> None:
        """Verify select_next_gemma_model() returns None for an unrecognized model ID."""
        result = select_next_gemma_model(failed_model="gpt-4o", backend=AIBackend.GOOGLE_AI_STUDIO)
        assert result is None

    def test_select_next_gemma_model_handles_normalized_ids(self) -> None:
        """Verify select_next_gemma_model() normalizes the failed_model before lookup.

        LM Studio format ("google/gemma-4-26b-a4b") should be normalized
        to "gemma-4-26b-a4b" for comparison against the priority list.
        """
        result = select_next_gemma_model(failed_model="google/gemma-4-26b-a4b", backend=AIBackend.LM_STUDIO)
        # Should still find 31B as the next model
        assert result == "google/gemma-4-31b"
