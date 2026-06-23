"""Tests for the streaming and request-sending call chain in :class:`SchemaAnalyzer`.

Covers the private helpers that build LLM request kwargs, resolve
per-model token budgets, accumulate streamed chunks, extract tool-call
results, and dispatch requests across backends (tool calling, JSON mode,
text mode). All LLM clients and HTTP calls are mocked — no real API
requests are made.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

try:
    from openai import APIError
    from sqlseed_ai.analyzer import SchemaAnalyzer
    from sqlseed_ai.config import AIBackend, AIConfig
except ImportError:
    pytest.skip("sqlseed-ai plugin not installed", allow_module_level=True)


class TestIsReasoningModelId:
    """Tests for :meth:`SchemaAnalyzer._is_reasoning_model_id`."""

    def test_is_reasoning_model_id_true(self) -> None:
        """Verify _is_reasoning_model_id() returns True for E2B/E4B model IDs."""
        assert SchemaAnalyzer._is_reasoning_model_id("gemma-4-e2b-it") is True
        assert SchemaAnalyzer._is_reasoning_model_id("gemma-4-e4b-it") is True
        assert SchemaAnalyzer._is_reasoning_model_id("google/gemma-4-e4b") is True
        assert SchemaAnalyzer._is_reasoning_model_id("gemma4:e2b") is True

    def test_is_reasoning_model_id_false(self) -> None:
        """Verify _is_reasoning_model_id() returns False for non-reasoning model IDs."""
        assert SchemaAnalyzer._is_reasoning_model_id("gemma-4-26b-a4b-it") is False
        assert SchemaAnalyzer._is_reasoning_model_id("gemma-4-31b-it") is False
        assert SchemaAnalyzer._is_reasoning_model_id("gemma-4-12b-it") is False
        assert SchemaAnalyzer._is_reasoning_model_id("gpt-4o") is False
        assert SchemaAnalyzer._is_reasoning_model_id(None) is False
        assert SchemaAnalyzer._is_reasoning_model_id("") is False


class TestResolveMaxTokensForModel:
    """Tests for :meth:`SchemaAnalyzer._resolve_max_tokens_for_model`."""

    def test_resolve_max_tokens_for_model_reasoning(self) -> None:
        """Verify _resolve_max_tokens_for_model() returns 768 for E2B/E4B on local backend."""
        config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-e4b")
        analyzer = SchemaAnalyzer(config=config)
        assert analyzer._resolve_max_tokens_for_model("google/gemma-4-e4b") == 768
        assert analyzer._resolve_max_tokens_for_model("gemma4:e2b") == 768

    def test_resolve_max_tokens_for_model_standard(self) -> None:
        """Verify _resolve_max_tokens_for_model() returns larger budgets for non-reasoning models."""
        config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-12b")
        analyzer = SchemaAnalyzer(config=config)
        # 12B model on local backend
        assert analyzer._resolve_max_tokens_for_model("google/gemma-4-12b") == 1024
        # 26B model on local backend
        assert analyzer._resolve_max_tokens_for_model("google/gemma-4-26b-a4b") == 2048

    def test_resolve_max_tokens_for_model_cloud_backend(self) -> None:
        """Verify _resolve_max_tokens_for_model() returns 4096 for cloud backends."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)
        assert analyzer._resolve_max_tokens_for_model("gemma-4-26b-a4b-it") == 4096

    def test_resolve_max_tokens_for_model_explicit_override(self) -> None:
        """Verify _resolve_max_tokens_for_model() respects explicit max_tokens setting."""
        config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-e4b", max_tokens=512)
        analyzer = SchemaAnalyzer(config=config)
        assert analyzer._resolve_max_tokens_for_model("google/gemma-4-e4b") == 512


class TestBuildLlmKwargs:
    """Tests for :meth:`SchemaAnalyzer._build_llm_kwargs`."""

    def test_build_llm_kwargs_includes_required_fields(self) -> None:
        """Verify _build_llm_kwargs() includes model, messages, max_tokens, temperature."""
        config = AIConfig(
            backend=AIBackend.GOOGLE_AI_STUDIO,
            model="gemma-4-26b-a4b-it",
            temperature=0.5,
        )
        analyzer = SchemaAnalyzer(config=config)
        kwargs = analyzer._build_llm_kwargs()
        assert kwargs["model"] == "gemma-4-26b-a4b-it"
        assert kwargs["messages"] == []  # Caller must set
        assert kwargs["max_tokens"] == 4096  # Cloud backend default
        assert kwargs["temperature"] == pytest.approx(0.5)

    def test_build_llm_kwargs_stream_flag(self) -> None:
        """Verify _build_llm_kwargs() adds stream=True when stream=True."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)
        kwargs = analyzer._build_llm_kwargs(stream=True)
        assert kwargs["stream"] is True

    def test_build_llm_kwargs_no_stream_by_default(self) -> None:
        """Verify _build_llm_kwargs() does not add stream key by default."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)
        kwargs = analyzer._build_llm_kwargs()
        assert "stream" not in kwargs

    def test_build_llm_kwargs_reasoning_effort_for_reasoning_model(self) -> None:
        """Verify _build_llm_kwargs() adds reasoning_effort='none' for reasoning models."""
        config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-e4b")
        analyzer = SchemaAnalyzer(config=config)
        kwargs = analyzer._build_llm_kwargs()
        assert kwargs["reasoning_effort"] == "none"

    def test_build_llm_kwargs_no_reasoning_effort_for_standard_model(self) -> None:
        """Verify _build_llm_kwargs() omits reasoning_effort for non-reasoning models."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)
        kwargs = analyzer._build_llm_kwargs()
        assert "reasoning_effort" not in kwargs

    def test_build_llm_kwargs_uses_provided_model(self) -> None:
        """Verify _build_llm_kwargs() uses the model parameter over config.model."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)
        kwargs = analyzer._build_llm_kwargs(model="gemma-4-e4b-it")
        assert kwargs["model"] == "gemma-4-e4b-it"
        # Should also pick up reasoning_effort for the provided model
        assert kwargs["reasoning_effort"] == "none"


class TestFindLocalFallbackModel:
    """Tests for :meth:`SchemaAnalyzer._find_local_fallback_model`."""

    def test_find_local_fallback_model_returns_next(self) -> None:
        """Verify _find_local_fallback_model() returns the next available local model."""
        config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-26b-a4b")
        analyzer = SchemaAnalyzer(config=config)
        # Mock detect_all_local_models on the class to return a list containing the fallback
        with patch.object(
            AIConfig,
            "detect_all_local_models",
            return_value=["google/gemma-4-e4b"],
        ):
            result = analyzer._find_local_fallback_model(
                current_model="google/gemma-4-26b-a4b",
                next_model="google/gemma-4-e4b",
            )
        assert result == "google/gemma-4-e4b"

    def test_find_local_fallback_model_returns_none_when_no_models(self) -> None:
        """Verify _find_local_fallback_model() returns None when no local models available."""
        config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-26b-a4b")
        analyzer = SchemaAnalyzer(config=config)
        with patch.object(AIConfig, "detect_all_local_models", return_value=[]):
            result = analyzer._find_local_fallback_model(
                current_model="google/gemma-4-26b-a4b",
                next_model="google/gemma-4-e4b",
            )
        assert result is None

    def test_find_local_fallback_model_returns_none_when_only_current_available(self) -> None:
        """Verify _find_local_fallback_model() returns None when only the failed model is available."""
        config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-26b-a4b")
        analyzer = SchemaAnalyzer(config=config)
        # Only the failed model is loaded locally
        with patch.object(
            AIConfig,
            "detect_all_local_models",
            return_value=["google/gemma-4-26b-a4b"],
        ):
            result = analyzer._find_local_fallback_model(
                current_model="google/gemma-4-26b-a4b",
                next_model="google/gemma-4-e4b",
            )
        assert result is None


class TestExtractToolCallResult:
    """Tests for :meth:`SchemaAnalyzer._extract_tool_call_result`."""

    def test_extract_tool_call_result_with_function_call(self) -> None:
        """Verify _extract_tool_call_result() extracts args from a successful FunctionCall."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        # Build a mock choice with a tool_calls list containing an analyze_schema call
        tool_call = MagicMock()
        tool_call.function.name = "analyze_schema"
        tool_call.function.arguments = '{"table_name": "users", "columns": []}'

        choice = MagicMock()
        choice.message.tool_calls = [tool_call]

        result = analyzer._extract_tool_call_result(choice)
        assert result is not None
        assert result["table_name"] == "users"
        assert result["columns"] == []

    def test_extract_tool_call_result_without_function_call(self) -> None:
        """Verify _extract_tool_call_result() returns None when no tool_calls present."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        choice = MagicMock()
        choice.message.tool_calls = None
        assert analyzer._extract_tool_call_result(choice) is None

        choice.message.tool_calls = []
        assert analyzer._extract_tool_call_result(choice) is None

    def test_extract_tool_call_result_skips_other_tools(self) -> None:
        """Verify _extract_tool_call_result() ignores tool calls not named analyze_schema."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        tool_call = MagicMock()
        tool_call.function.name = "other_function"
        tool_call.function.arguments = '{"foo": "bar"}'

        choice = MagicMock()
        choice.message.tool_calls = [tool_call]
        assert analyzer._extract_tool_call_result(choice) is None

    def test_extract_tool_call_result_handles_invalid_json(self) -> None:
        """Verify _extract_tool_call_result() returns None when tool call args are not valid JSON."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        tool_call = MagicMock()
        tool_call.function.name = "analyze_schema"
        tool_call.function.arguments = "not valid json {{{"

        choice = MagicMock()
        choice.message.tool_calls = [tool_call]
        assert analyzer._extract_tool_call_result(choice) is None


class TestCollectStreamChunks:
    """Tests for :meth:`SchemaAnalyzer._collect_stream_chunks`."""

    def test_collect_stream_chunks_accumulates_content(self) -> None:
        """Verify _collect_stream_chunks() accumulates content from a stream of chunks."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        # Build mock stream chunks
        def make_chunk(content: str) -> Any:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = content
            chunk.choices[0].delta.reasoning_content = None
            return chunk

        stream = [make_chunk('{"name": '), make_chunk('"users"}')]
        content, token_count = analyzer._collect_stream_chunks(stream, None)
        assert content == '{"name": "users"}'
        assert token_count == 2

    def test_collect_stream_chunks_skips_empty_choices(self) -> None:
        """Verify _collect_stream_chunks() skips chunks with no choices."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        empty_chunk = MagicMock()
        empty_chunk.choices = []

        content_chunk = MagicMock()
        content_chunk.choices = [MagicMock()]
        content_chunk.choices[0].delta.content = "hello"
        content_chunk.choices[0].delta.reasoning_content = None

        content, token_count = analyzer._collect_stream_chunks([empty_chunk, content_chunk], None)
        assert content == "hello"
        assert token_count == 1

    def test_collect_stream_chunks_skips_reasoning_content(self) -> None:
        """Verify _collect_stream_chunks() skips reasoning_content tokens but counts them."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        reasoning_chunk = MagicMock()
        reasoning_chunk.choices = [MagicMock()]
        reasoning_chunk.choices[0].delta.content = None
        reasoning_chunk.choices[0].delta.reasoning_content = "thinking..."

        content_chunk = MagicMock()
        content_chunk.choices = [MagicMock()]
        content_chunk.choices[0].delta.content = "answer"
        content_chunk.choices[0].delta.reasoning_content = None

        content, token_count = analyzer._collect_stream_chunks(
            [reasoning_chunk, content_chunk], None
        )
        # Only the content token is accumulated, reasoning is skipped
        assert content == "answer"
        assert token_count == 1

    def test_collect_stream_chunks_invokes_progress_callback(self) -> None:
        """Verify _collect_stream_chunks() invokes the progress callback for each content token."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = "tok"
        chunk.choices[0].delta.reasoning_content = None

        progress_calls: list[tuple[str, dict[str, Any]]] = []

        def on_progress(phase: str, info: dict[str, Any]) -> None:
            progress_calls.append((phase, info))

        analyzer._collect_stream_chunks([chunk, chunk], on_progress)
        assert len(progress_calls) == 2
        assert progress_calls[0][0] == "streaming"
        assert progress_calls[0][1]["token"] == "tok"
        assert progress_calls[0][1]["count"] == 1
        assert progress_calls[1][1]["count"] == 2


class TestSendLlmRequest:
    """Tests for :meth:`SchemaAnalyzer._send_llm_request` and :meth:`_send_with_json_mode`."""

    def test_send_llm_request_returns_response_for_local_backend(self) -> None:
        """Verify _send_llm_request() returns response from text mode for local backends.

        Local backends (LM Studio, Ollama) skip tool calling and JSON mode,
        using text mode directly via _create_with_reasoning_fallback.
        """
        config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-12b")
        analyzer = SchemaAnalyzer(config=config)

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        kwargs: dict[str, Any] = {
            "model": "google/gemma-4-12b",
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 1024,
            "temperature": 0.3,
        }
        result = analyzer._send_llm_request(mock_client, kwargs)
        assert result is mock_response
        mock_client.chat.completions.create.assert_called_once()

    def test_send_llm_request_uses_tool_calling_for_google_ai_studio(self) -> None:
        """Verify _send_llm_request() attempts tool calling for Google AI Studio backend."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        mock_client = MagicMock()
        # First call (tool calling) returns a choice with no tool_calls and no content,
        # so _try_tool_calling returns None and we fall back to JSON mode.
        tool_response = MagicMock()
        tool_response.choices = []  # No choices -> _try_tool_calling returns None
        # Second call (JSON mode) returns a valid response
        json_response = MagicMock()
        mock_client.chat.completions.create.side_effect = [tool_response, json_response]

        kwargs: dict[str, Any] = {
            "model": "gemma-4-26b-a4b-it",
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 4096,
            "temperature": 0.3,
        }
        result = analyzer._send_llm_request(mock_client, kwargs)
        assert result is json_response
        # Two calls: one for tool calling, one for JSON mode
        assert mock_client.chat.completions.create.call_count == 2

    def test_send_with_json_mode_returns_response(self) -> None:
        """Verify _send_with_json_mode() sets response_format and returns the response."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        kwargs: dict[str, Any] = {
            "model": "gemma-4-26b-a4b-it",
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 4096,
            "temperature": 0.3,
        }
        result = analyzer._send_with_json_mode(mock_client, kwargs)
        assert result is mock_response
        # Verify response_format was added
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["response_format"] == {"type": "json_object"}

    def test_send_with_json_mode_falls_back_to_text_on_error(self) -> None:
        """Verify _send_with_json_mode() falls back to text mode when JSON mode fails."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        mock_client = MagicMock()
        # First call (with response_format) raises a 400 APIError
        # Second call (without response_format) succeeds
        mock_response = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            APIError("400 Bad Request: response_format not supported", request=MagicMock(), body=None),
            mock_response,
        ]

        kwargs: dict[str, Any] = {
            "model": "gemma-4-26b-a4b-it",
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 4096,
            "temperature": 0.3,
        }
        result = analyzer._send_with_json_mode(mock_client, kwargs)
        assert result is mock_response
        # Verify response_format was removed before the retry
        second_call_kwargs = mock_client.chat.completions.create.call_args_list[1].kwargs
        assert "response_format" not in second_call_kwargs
