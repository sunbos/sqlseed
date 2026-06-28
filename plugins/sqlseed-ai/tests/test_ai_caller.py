"""Tests for the LLM caller mixin in sqlseed_ai.analyzer._caller.

Covers ``_find_local_fallback_model`` (config guard + fallback-chain walk),
``_ensure_config`` (lazy env init), ``_call_with_fallback`` (config guard +
local-backend model verification), ``_resolve_max_tokens_for_model`` /
``_build_llm_kwargs`` config guards, ``_create_with_reasoning_fallback``
(reasoning_effort retry), and ``_call_llm_once`` (config guard, context
overflow, empty choices, reasoning content, empty content). All LLM clients
and HTTP calls are mocked — no real API requests are made.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

try:
    from openai import APIConnectionError, APIError, APITimeoutError
    from sqlseed_ai.analyzer import SchemaAnalyzer
    from sqlseed_ai.config import AIBackend, AIConfig
    from sqlseed_ai.exceptions import ContextOverflowError
except ImportError:
    pytest.skip("sqlseed-ai plugin not installed", allow_module_level=True)


def _make_request_obj() -> Any:
    """Build a minimal mock request object for OpenAI exception constructors."""
    return MagicMock()


class TestFindLocalFallbackModelConfigGuard:
    """Tests for the config guard in _find_local_fallback_model."""

    def test_find_local_fallback_model_raises_runtime_error_when_config_none(self) -> None:
        """Verify _find_local_fallback_model() raises RuntimeError when _config is None."""
        analyzer = SchemaAnalyzer(config=None)
        with pytest.raises(RuntimeError, match="AIConfig must be initialized before checking local fallback"):
            analyzer._find_local_fallback_model("model_a", "model_b")


class TestFindLocalFallbackModelWalksChain:
    """Tests for the fallback-chain walk in _find_local_fallback_model.

    When the immediate ``next_model`` is not available locally but other models
    ARE loaded, the method walks the Gemma 4 priority chain via
    ``select_next_gemma_model`` until it finds the first locally-available model.
    """

    def test_walks_chain_to_find_first_available_local_model(self) -> None:
        """Verify the fallback chain is walked until a local model is found.

        Setup: current model is 26B, next_model is 31B (not loaded locally),
        but E4B is loaded. The walk should traverse 31B -> 12B -> E4B and
        return the actual local model ID.
        """
        config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-26b-a4b")
        analyzer = SchemaAnalyzer(config=config)

        with patch.object(
            AIConfig,
            "detect_all_local_models",
            return_value=["google/gemma-4-e4b"],
        ):
            result = analyzer._find_local_fallback_model(
                current_model="google/gemma-4-26b-a4b",
                next_model="gemma-4-31b-it",
            )
        # Should walk 31B -> 12B -> E4B and find E4B.
        assert result == "google/gemma-4-e4b"

    def test_walks_chain_returns_none_when_no_gemma_match_in_local_map(self) -> None:
        """Verify None is returned when the chain is walked but no Gemma model matches.

        Setup: current model is 26B, next_model is 31B, and the only other
        locally-loaded model is a non-Gemma model (e.g. "llama-3"). The walk
        traverses the entire Gemma 4 chain (31B -> 12B -> E4B -> E2B) without
        finding a match, so the method returns None.
        """
        config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-26b-a4b")
        analyzer = SchemaAnalyzer(config=config)

        with patch.object(
            AIConfig,
            "detect_all_local_models",
            return_value=["llama-3-model"],
        ):
            result = analyzer._find_local_fallback_model(
                current_model="google/gemma-4-26b-a4b",
                next_model="gemma-4-31b-it",
            )
        # The entire Gemma 4 chain is exhausted without matching "llama-3-model".
        assert result is None

    def test_walks_chain_finds_model_after_skipping_unavailable(self) -> None:
        """Verify the walk skips unavailable models and finds a later one.

        Setup: current model is 26B, next_model is 31B, and only 12B is loaded
        locally (not 31B or E4B). The walk should find 12B.
        """
        config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-26b-a4b")
        analyzer = SchemaAnalyzer(config=config)

        with patch.object(
            AIConfig,
            "detect_all_local_models",
            return_value=["google/gemma-4-12b"],
        ):
            result = analyzer._find_local_fallback_model(
                current_model="google/gemma-4-26b-a4b",
                next_model="gemma-4-31b-it",
            )
        # Walk: 31B (not local) -> 12B (local!) -> return "google/gemma-4-12b".
        assert result == "google/gemma-4-12b"


class TestEnsureConfig:
    """Tests for :meth:`SchemaAnalyzer._ensure_config` lazy initialization."""

    def test_ensure_config_loads_from_env_when_config_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify _ensure_config() calls AIConfig.from_env() when _config is None."""
        # Provide env vars so from_env() produces a config with a real API key.
        monkeypatch.setenv("SQLSEED_AI_API_KEY", "sk-env-key")
        monkeypatch.setenv("SQLSEED_AI_MODEL", "gemma-4-26b-a4b-it")
        monkeypatch.delenv("SQLSEED_AI_BASE_URL", raising=False)
        monkeypatch.delenv("SQLSEED_AI_BACKEND", raising=False)

        analyzer = SchemaAnalyzer(config=None)
        assert analyzer._config is None

        analyzer._ensure_config()

        assert analyzer._config is not None
        assert analyzer._config.api_key == "sk-env-key"

    def test_ensure_config_raises_value_error_when_no_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify _ensure_config() raises ValueError when no API key is configured."""
        monkeypatch.delenv("SQLSEED_AI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("SQLSEED_AI_BACKEND", raising=False)

        analyzer = SchemaAnalyzer(config=None)
        with pytest.raises(ValueError, match="AI API key not configured"):
            analyzer._ensure_config()

    def test_ensure_config_resolves_model_for_existing_config(self) -> None:
        """Verify _ensure_config() resolves the model when config already exists."""
        config = AIConfig(
            backend=AIBackend.GOOGLE_AI_STUDIO,
            api_key="sk-test",
            model="gemma-4-26b-a4b-it",
        )
        analyzer = SchemaAnalyzer(config=config)
        analyzer._ensure_config()
        assert config.model == "gemma-4-26b-a4b-it"


class TestCallWithFallbackConfigGuard:
    """Tests for the config guard in _call_with_fallback."""

    def test_call_with_fallback_raises_runtime_error_when_config_none(self) -> None:
        """Verify _call_with_fallback() raises RuntimeError when _config is None."""
        analyzer = SchemaAnalyzer(config=None)

        def call_fn(_model: str) -> dict[str, Any]:
            return {}

        with pytest.raises(RuntimeError, match="AIConfig must be initialized before this operation"):
            analyzer._call_with_fallback(call_fn)


class TestCallWithFallbackLocalBackend:
    """Tests for local-backend model verification in _call_with_fallback.

    On LM Studio / Ollama, before switching to a fallback model the caller
    verifies via ``_find_local_fallback_model`` that the model is actually
    loaded locally. If not, a RuntimeError is raised immediately.
    """

    def test_local_backend_raises_when_no_fallback_model_available(self) -> None:
        """Verify RuntimeError is raised when no alternative local model exists.

        Setup: LM Studio backend, only the current model is loaded locally.
        The first call raises APITimeoutError; _find_local_fallback_model
        returns None because no other model is available.
        """
        config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-26b-a4b")
        analyzer = SchemaAnalyzer(config=config)

        call_count = 0

        def call_fn(_model: str) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            raise APITimeoutError(request=_make_request_obj())

        with (
            patch(
                "sqlseed_ai.analyzer._caller.select_next_gemma_model",
                return_value="google/gemma-4-31b",
            ),
            patch.object(
                AIConfig,
                "detect_all_local_models",
                return_value=["google/gemma-4-26b-a4b"],
            ),
            pytest.raises(RuntimeError, match="No other model available on local backend"),
        ):
            analyzer._call_with_fallback(call_fn)

        # Only the first attempt should have been made before failing.
        assert call_count == 1

    def test_local_backend_succeeds_when_fallback_model_available(self) -> None:
        """Verify the call retries with the verified fallback model on local backends.

        Setup: LM Studio backend, current model is 26B, E4B is also loaded.
        The first call (26B) raises APITimeoutError; _find_local_fallback_model
        returns E4B; the second call (E4B) succeeds.
        """
        config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-26b-a4b")
        analyzer = SchemaAnalyzer(config=config)

        call_models: list[str] = []

        def call_fn(model: str) -> dict[str, Any]:
            call_models.append(model)
            if len(call_models) == 1:
                raise APITimeoutError(request=_make_request_obj())
            return {"table_name": "users", "columns": []}

        with (
            patch(
                "sqlseed_ai.analyzer._caller.select_next_gemma_model",
                return_value="google/gemma-4-e4b",
            ),
            patch.object(
                AIConfig,
                "detect_all_local_models",
                return_value=["google/gemma-4-26b-a4b", "google/gemma-4-e4b"],
            ),
        ):
            result = analyzer._call_with_fallback(call_fn)

        assert result == {"table_name": "users", "columns": []}
        # First call with the original model, second with the fallback.
        assert call_models == ["google/gemma-4-26b-a4b", "google/gemma-4-e4b"]


class TestResolveMaxTokensForModelNoConfig:
    """Tests for _resolve_max_tokens_for_model when config is None."""

    def test_resolve_max_tokens_returns_2048_when_config_none(self) -> None:
        """Verify _resolve_max_tokens_for_model() returns 2048 when _config is None."""
        analyzer = SchemaAnalyzer(config=None)
        assert analyzer._resolve_max_tokens_for_model("any-model") == 2048


class TestBuildLlmKwargsConfigGuard:
    """Tests for the config guard in _build_llm_kwargs."""

    def test_build_llm_kwargs_raises_runtime_error_when_config_none(self) -> None:
        """Verify _build_llm_kwargs() raises RuntimeError when _config is None."""
        analyzer = SchemaAnalyzer(config=None)
        with pytest.raises(RuntimeError, match="AIConfig must be initialized before this operation"):
            analyzer._build_llm_kwargs()


class TestCreateWithReasoningFallback:
    """Tests for _create_with_reasoning_fallback reasoning_effort retry.

    Some backends (older LM Studio) don't support ``reasoning_effort``. When a
    400 APIError classified as ``ModelFallbackError`` is raised and
    ``reasoning_effort`` is in kwargs, the call is retried without it.
    """

    def test_retries_without_reasoning_effort_on_model_fallback_error(self) -> None:
        """Verify reasoning_effort is stripped and the call retried on a 400 error."""
        config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-e4b")
        analyzer = SchemaAnalyzer(config=config)

        mock_client = MagicMock()
        success_response = MagicMock()
        # First call raises an APIError mentioning reasoning_effort (classified
        # as ModelFallbackError); second call succeeds.
        mock_client.chat.completions.create.side_effect = [
            APIError(
                "400 Bad Request: reasoning_effort not supported",
                request=_make_request_obj(),
                body=None,
            ),
            success_response,
        ]

        kwargs: dict[str, Any] = {
            "model": "google/gemma-4-e4b",
            "messages": [],
            "reasoning_effort": "none",
        }
        result = analyzer._create_with_reasoning_fallback(mock_client, kwargs)

        assert result is success_response
        assert mock_client.chat.completions.create.call_count == 2
        # The retry call should NOT contain reasoning_effort.
        second_call_kwargs = mock_client.chat.completions.create.call_args_list[1].kwargs
        assert "reasoning_effort" not in second_call_kwargs
        # The original kwargs dict should also have had reasoning_effort removed.
        assert "reasoning_effort" not in kwargs

    def test_reraises_api_error_without_reasoning_effort_in_kwargs(self) -> None:
        """Verify APIError is re-raised when reasoning_effort is not in kwargs."""
        config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-12b")
        analyzer = SchemaAnalyzer(config=config)

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = APIError(
            "400 Bad Request: response_format not supported",
            request=_make_request_obj(),
            body=None,
        )

        kwargs: dict[str, Any] = {
            "model": "google/gemma-4-12b",
            "messages": [],
        }
        with pytest.raises(APIError, match="400 Bad Request"):
            analyzer._create_with_reasoning_fallback(mock_client, kwargs)
        # Only one call — no retry since reasoning_effort was not in kwargs.
        assert mock_client.chat.completions.create.call_count == 1

    def test_reraises_api_error_when_not_model_fallback(self) -> None:
        """Verify APIError is re-raised when the error is not a ModelFallbackError.

        A 500 Internal Server Error does not match the ModelFallbackError
        classifier, so it should propagate even when reasoning_effort is set.
        """
        config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-e4b")
        analyzer = SchemaAnalyzer(config=config)

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = APIError(
            "500 Internal Server Error",
            request=_make_request_obj(),
            body=None,
        )

        kwargs: dict[str, Any] = {
            "model": "google/gemma-4-e4b",
            "messages": [],
            "reasoning_effort": "none",
        }
        with pytest.raises(APIError, match="500 Internal Server Error"):
            analyzer._create_with_reasoning_fallback(mock_client, kwargs)
        # reasoning_effort should still be in kwargs (not stripped).
        assert "reasoning_effort" in kwargs
        assert mock_client.chat.completions.create.call_count == 1


class TestCallLlmOnceConfigGuard:
    """Tests for the config guard in _call_llm_once."""

    def test_call_llm_once_raises_runtime_error_when_config_none(self) -> None:
        """Verify _call_llm_once() raises RuntimeError when _config is None."""
        analyzer = SchemaAnalyzer(config=None)
        with pytest.raises(RuntimeError, match="AIConfig must be initialized before calling LLM"):
            analyzer._call_llm_once([])


class TestCallLlmOnceContextOverflow:
    """Tests for ContextOverflowError handling in _call_llm_once."""

    def test_call_llm_once_raises_context_overflow_error(self) -> None:
        """Verify errors classified as ContextOverflowError are re-raised as that type."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        overflow_err = ValueError("context length exceed maximum")

        with (
            patch("sqlseed_ai.analyzer._caller.get_openai_client", return_value=MagicMock()),
            patch.object(analyzer, "_build_llm_kwargs", return_value={}),
            patch.object(analyzer, "_send_llm_request", side_effect=overflow_err),
            pytest.raises(ContextOverflowError),
        ):
            analyzer._call_llm_once([], model="gemma-4-26b-a4b-it")

    def test_call_llm_once_reraises_api_timeout_error(self) -> None:
        """Verify APITimeoutError from _send_llm_request is re-raised unchanged."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        timeout_err = APITimeoutError(request=_make_request_obj())

        with (
            patch("sqlseed_ai.analyzer._caller.get_openai_client", return_value=MagicMock()),
            patch.object(analyzer, "_build_llm_kwargs", return_value={}),
            patch.object(analyzer, "_send_llm_request", side_effect=timeout_err),
            pytest.raises(APITimeoutError),
        ):
            analyzer._call_llm_once([])

    def test_call_llm_once_wraps_other_errors_as_runtime_error(self) -> None:
        """Verify non-timeout, non-overflow errors are wrapped as RuntimeError."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        other_err = OSError("disk write failed")

        with (
            patch("sqlseed_ai.analyzer._caller.get_openai_client", return_value=MagicMock()),
            patch.object(analyzer, "_build_llm_kwargs", return_value={}),
            patch.object(analyzer, "_send_llm_request", side_effect=other_err),
            pytest.raises(RuntimeError, match="LLM API call failed"),
        ):
            analyzer._call_llm_once([])


class TestCallLlmOnceResponseHandling:
    """Tests for _call_llm_once response inspection (choices, content, reasoning)."""

    def test_call_llm_once_raises_runtime_error_when_no_choices(self) -> None:
        """Verify RuntimeError is raised when the response has no choices."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        mock_response = MagicMock()
        mock_response.choices = []

        with (
            patch("sqlseed_ai.analyzer._caller.get_openai_client", return_value=MagicMock()),
            patch.object(analyzer, "_build_llm_kwargs", return_value={}),
            patch.object(analyzer, "_send_llm_request", return_value=mock_response),
            pytest.raises(RuntimeError, match="LLM returned no choices"),
        ):
            analyzer._call_llm_once([])

    def test_call_llm_once_returns_empty_dict_when_content_none(self) -> None:
        """Verify {} is returned when the message content is None."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        mock_message = MagicMock()
        mock_message.content = None
        mock_message.reasoning_content = None

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = mock_message

        with (
            patch("sqlseed_ai.analyzer._caller.get_openai_client", return_value=MagicMock()),
            patch.object(analyzer, "_build_llm_kwargs", return_value={}),
            patch.object(analyzer, "_send_llm_request", return_value=mock_response),
            patch.object(analyzer, "_parse_json_response") as mock_parse,
        ):
            result = analyzer._call_llm_once([])

        assert result == {}
        # _parse_json_response should NOT be called when content is None.
        mock_parse.assert_not_called()

    def test_call_llm_once_logs_reasoning_content_when_present(self) -> None:
        """Verify reasoning_content is detected and logged without breaking the flow.

        When the response message has ``reasoning_content``, the method logs a
        debug message and then proceeds to parse the regular content.
        """
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        mock_message = MagicMock()
        mock_message.content = '{"table_name": "users"}'
        mock_message.reasoning_content = "chain of thought..."  # truthy

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = mock_message

        expected = {"table_name": "users"}
        with (
            patch("sqlseed_ai.analyzer._caller.get_openai_client", return_value=MagicMock()),
            patch.object(analyzer, "_build_llm_kwargs", return_value={}),
            patch.object(analyzer, "_send_llm_request", return_value=mock_response),
            patch.object(analyzer, "_parse_json_response", return_value=expected),
        ):
            result = analyzer._call_llm_once([])

        # The parsed result should be returned even when reasoning_content is present.
        assert result is expected

    def test_call_llm_once_returns_parsed_dict_on_success(self) -> None:
        """Verify _call_llm_once() returns the parsed JSON dict on a normal response."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        mock_message = MagicMock()
        mock_message.content = '{"table_name": "orders", "columns": []}'
        mock_message.reasoning_content = None

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = mock_message

        expected = {"table_name": "orders", "columns": []}
        with (
            patch("sqlseed_ai.analyzer._caller.get_openai_client", return_value=MagicMock()),
            patch.object(analyzer, "_build_llm_kwargs", return_value={}),
            patch.object(analyzer, "_send_llm_request", return_value=mock_response),
            patch.object(analyzer, "_parse_json_response", return_value=expected),
        ):
            result = analyzer._call_llm_once(
                [{"role": "user", "content": "analyze"}],
                model="gemma-4-26b-a4b-it",
            )

        assert result is expected

    def test_call_llm_once_passes_model_to_build_llm_kwargs(self) -> None:
        """Verify the model parameter is forwarded to _build_llm_kwargs."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        mock_message = MagicMock()
        mock_message.content = None
        mock_message.reasoning_content = None
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = mock_message

        with (
            patch("sqlseed_ai.analyzer._caller.get_openai_client", return_value=MagicMock()),
            patch.object(analyzer, "_build_llm_kwargs", return_value={}) as mock_build,
            patch.object(analyzer, "_send_llm_request", return_value=mock_response),
        ):
            analyzer._call_llm_once([], model="gemma-4-e4b-it")

        mock_build.assert_called_once_with(model="gemma-4-e4b-it")


class TestCallLlmEntryAndFallback:
    """Tests for the public call_llm entry point and _call_with_fallback retry."""

    def test_call_llm_succeeds_on_first_try(self) -> None:
        """Verify call_llm() returns the result when the first attempt succeeds."""
        config = AIConfig(api_key="sk-test", model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        expected = {"table_name": "users", "columns": []}
        with patch.object(analyzer, "_call_llm_once", return_value=expected) as mock_once:
            result = analyzer.call_llm([{"role": "user", "content": "hi"}])

        assert result is expected
        mock_once.assert_called_once()

    def test_call_llm_falls_back_on_connection_error(self) -> None:
        """Verify call_llm() falls back to the next model on APIConnectionError."""
        config = AIConfig(api_key="sk-test", model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        call_count = 0

        def mock_call_llm_once(_self, _messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise APIConnectionError(request=_make_request_obj())
            return {"table_name": "users", "columns": []}

        with (
            patch.object(SchemaAnalyzer, "_call_llm_once", mock_call_llm_once),
            patch(
                "sqlseed_ai.analyzer._caller.select_next_gemma_model",
                return_value="gemma-4-31b-it",
            ),
        ):
            result = analyzer.call_llm([{"role": "user", "content": "hi"}])

        assert result == {"table_name": "users", "columns": []}
        assert call_count == 2

    def test_call_llm_exhausts_fallback_attempts(self) -> None:
        """Verify RuntimeError is raised after exhausting all fallback attempts."""
        config = AIConfig(api_key="sk-test", model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        def mock_call_llm_once(_self, _messages, **_kwargs):
            raise APITimeoutError(request=_make_request_obj())

        # select_next_gemma_model returns a new model on the first two calls
        # (so the loop retries) and None on the third (so it raises).
        next_models = iter(["gemma-4-31b-it", "gemma-4-12b-it", None])

        def mock_select_next(*_args, **_kwargs):
            return next(next_models)

        with (
            patch.object(SchemaAnalyzer, "_call_llm_once", mock_call_llm_once),
            patch(
                "sqlseed_ai.analyzer._caller.select_next_gemma_model",
                side_effect=mock_select_next,
            ),
            pytest.raises(RuntimeError, match="LLM API call failed after trying"),
        ):
            analyzer.call_llm([{"role": "user", "content": "hi"}])

    def test_call_llm_raises_after_max_fallback_attempts_with_models_remaining(self) -> None:
        """Verify RuntimeError is raised when the fallback loop completes all attempts.

        Unlike the test above (where select_next_gemma_model returns None and
        triggers the early RuntimeError inside the loop), this test exercises
        the post-loop RuntimeError at line 148: select_next_gemma_model keeps
        returning non-None models, so the loop runs all _MAX_FALLBACK_ATTEMPTS
        iterations and then falls through to the final raise.
        """
        config = AIConfig(api_key="sk-test", model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        def mock_call_llm_once(_self, _messages, **_kwargs):
            raise APITimeoutError(request=_make_request_obj())

        # Always return a non-None model so the loop never hits the
        # `if next_model is None` early-exit; it must fall through to line 148.
        with (
            patch.object(SchemaAnalyzer, "_call_llm_once", mock_call_llm_once),
            patch(
                "sqlseed_ai.analyzer._caller.select_next_gemma_model",
                return_value="gemma-4-e2b-it",
            ),
            pytest.raises(RuntimeError, match="LLM API call failed after 3 fallback attempts"),
        ):
            analyzer.call_llm([{"role": "user", "content": "hi"}])
