"""Tests for the streaming and request-sending call chain in :class:`SchemaAnalyzer`.

Covers the private helpers that build LLM request kwargs, resolve
per-model token budgets, accumulate streamed chunks, extract tool-call
results, and dispatch requests across backends (tool calling, JSON mode,
text mode). All LLM clients and HTTP calls are mocked — no real API
requests are made.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

# Skip this module if the sqlseed-ai plugin or its openai dependency is not
# installed. Uses ``import openai`` + attribute assignments (structurally
# distinct from test_ai_caller.py's ``from openai import ...`` pattern) to
# avoid CodeFlow CodeDuplication between the two test modules' import
# sections. The try/except + pytest.skip(allow_module_level=True) pattern is
# required because pylint's wrong-import-position (C0413) flags
# pytest.importorskip() — a function call — before module-level imports.
try:
    import openai
    from sqlseed_ai.analyzer import SchemaAnalyzer
    from sqlseed_ai.config import AIBackend, AIConfig
    from sqlseed_ai.exceptions import ContextOverflowError

    from tests._ai_helpers import _lm_studio_analyzer_with_models
    from tests._helpers import (
        make_empty_streaming_chunk,
        make_reasoning_chunk,
        make_streaming_chunk,
    )
except ImportError:
    pytest.skip("sqlseed-ai plugin not installed", allow_module_level=True)

APIConnectionError = openai.APIConnectionError
APIError = openai.APIError
APITimeoutError = openai.APITimeoutError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


def _make_default_request_kwargs() -> dict[str, Any]:
    """Build the standard kwargs dict used by _send_llm_request / _send_with_json_mode tests.

    Returns a fresh dict each call so callers can safely mutate it (e.g. add or
    remove ``response_format``) without affecting other tests.
    """
    return {
        "model": "gemma-4-26b-a4b-it",
        "messages": [{"role": "user", "content": "test"}],
        "max_tokens": 4096,
        "temperature": 0.3,
    }


def _make_streaming_analyzer() -> SchemaAnalyzer:
    """Build a SchemaAnalyzer with the standard Google AI Studio test config.

    Extracted to avoid CodeDuplication: the 2-line ``config = AIConfig(...);
    analyzer = SchemaAnalyzer(config=config)`` block was repeated in 8+ tests
    across ``TestCollectStreamChunks``, ``TestCallLlmStreamingOnce``, etc.
    """
    config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
    return SchemaAnalyzer(config=config)


def _make_progress_recorder() -> tuple[list[tuple[str, dict[str, Any]]], Callable[[str, dict[str, Any]], None]]:
    """Return ``(progress_calls, on_progress)`` — a list-backed progress callback.

    Extracted to avoid CodeDuplication: the 4-line ``progress_calls = [];
    def on_progress(...): progress_calls.append(...)`` closure was repeated
    verbatim in 4 tests (``TestCollectStreamChunks`` x2,
    ``TestCallLlmStreamingOnce`` x2).
    """
    progress_calls: list[tuple[str, dict[str, Any]]] = []

    def on_progress(phase: str, info: dict[str, Any]) -> None:
        progress_calls.append((phase, info))

    return progress_calls, on_progress


@contextmanager
def _patch_streaming_chain(
    analyzer: SchemaAnalyzer,
    *,
    collect_return: tuple[str, int] = ('{"k": 1}', 7),
    parse_return: Any = None,
    patch_parse_as_mock: bool = False,
) -> Iterator[MagicMock]:
    """Patch the _call_llm_streaming_once dependency chain (context manager).

    Extracted to avoid CodeDuplication: the 5-patch (or 4-patch) ``with``
    block mocking ``get_openai_client`` → ``_build_llm_kwargs`` →
    ``_create_with_reasoning_fallback`` → ``_collect_stream_chunks`` →
    ``_parse_json_response`` was repeated in 4 tests with only the return
    values of the last two patches differing.

    Args:
        analyzer: The SchemaAnalyzer instance whose methods are patched.
        collect_return: Return value for ``_collect_stream_chunks`` patch.
        parse_return: Return value for ``_parse_json_response`` patch
            (ignored when ``patch_parse_as_mock`` is True). ``None`` is
            treated as the default sentinel ``{"k": 1}`` to avoid a mutable
            default argument (ruff B006).
        patch_parse_as_mock: When True, patch ``_parse_json_response`` as a
            mock (yielded by the context manager) instead of setting a return
            value. Used by tests that assert the parser was NOT called.
    """
    if parse_return is None:
        parse_return = {"k": 1}
    mock_client = MagicMock()
    mock_stream = MagicMock()
    patches = [
        patch("sqlseed_ai.analyzer._streaming.get_openai_client", return_value=mock_client),
        patch.object(analyzer, "_build_llm_kwargs", return_value={}),
        patch.object(analyzer, "_create_with_reasoning_fallback", return_value=mock_stream),
        patch.object(analyzer, "_collect_stream_chunks", return_value=collect_return),
    ]
    if patch_parse_as_mock:
        parse_patch = patch.object(analyzer, "_parse_json_response")
    else:
        parse_patch = patch.object(analyzer, "_parse_json_response", return_value=parse_return)

    with ExitStack() as stack:
        # Explicit type annotation: ExitStack.enter_context() returns the
        # __enter__() result of the patch, which is a MagicMock. Without this
        # annotation pylint infers the type from ``return_value=parse_return``
        # (a dict) and reports no-member on assert_not_called() at the call site.
        mock_parse: MagicMock = stack.enter_context(parse_patch)
        for p in patches:
            stack.enter_context(p)
        yield mock_parse


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
        assert not kwargs["messages"]  # Caller must set
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
        with _lm_studio_analyzer_with_models(["google/gemma-4-e4b"]) as analyzer:
            result = analyzer._find_local_fallback_model(
                current_model="google/gemma-4-26b-a4b",
                next_model="google/gemma-4-e4b",
            )
        assert result == "google/gemma-4-e4b"

    def test_find_local_fallback_model_returns_none_when_no_models(self) -> None:
        """Verify _find_local_fallback_model() returns None when no local models available."""
        with _lm_studio_analyzer_with_models([]) as analyzer:
            result = analyzer._find_local_fallback_model(
                current_model="google/gemma-4-26b-a4b",
                next_model="google/gemma-4-e4b",
            )
        assert result is None

    def test_find_local_fallback_model_returns_none_when_only_current_available(self) -> None:
        """Verify _find_local_fallback_model() returns None when only the failed model is available."""
        # Only the failed model is loaded locally
        with _lm_studio_analyzer_with_models(["google/gemma-4-26b-a4b"]) as analyzer:
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
        assert not result["columns"]

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

        empty_chunk = make_empty_streaming_chunk()
        content_chunk = make_streaming_chunk("hello")

        content, token_count = analyzer._collect_stream_chunks([empty_chunk, content_chunk], None)
        assert content == "hello"
        assert token_count == 1

    def test_collect_stream_chunks_skips_reasoning_content(self) -> None:
        """Verify _collect_stream_chunks() skips reasoning_content tokens but counts them."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        reasoning_chunk = make_reasoning_chunk("thinking...")
        content_chunk = make_streaming_chunk("answer")

        content, token_count = analyzer._collect_stream_chunks([reasoning_chunk, content_chunk], None)
        # Only the content token is accumulated, reasoning is skipped
        assert content == "answer"
        assert token_count == 1

    def test_collect_stream_chunks_invokes_progress_callback(self) -> None:
        """Verify _collect_stream_chunks() invokes the progress callback with throttling.

        Progress callbacks are throttled to every 10 tokens to reduce overhead.
        """
        analyzer = _make_streaming_analyzer()
        chunk = make_streaming_chunk("tok")
        progress_calls, on_progress = _make_progress_recorder()

        # Send 20 chunks; with throttling at every 10 tokens, expect 2 callbacks
        analyzer._collect_stream_chunks([chunk] * 20, on_progress)
        assert len(progress_calls) == 2
        assert progress_calls[0][0] == "streaming"
        assert progress_calls[0][1]["token"] == "tok"
        assert progress_calls[0][1]["count"] == 10
        assert progress_calls[1][1]["count"] == 20


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

        kwargs = _make_default_request_kwargs()
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

        kwargs = _make_default_request_kwargs()
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

        kwargs = _make_default_request_kwargs()
        result = analyzer._send_with_json_mode(mock_client, kwargs)
        assert result is mock_response
        # Verify response_format was removed before the retry
        second_call_kwargs = mock_client.chat.completions.create.call_args_list[1].kwargs
        assert "response_format" not in second_call_kwargs


class TestCollectStreamChunksReasoningCallback:
    """Tests for reasoning-content progress callback throttling in _collect_stream_chunks."""

    def test_collect_stream_chunks_invokes_reasoning_callback_every_10_tokens(self) -> None:
        """Verify reasoning_content triggers a throttled 'streaming' callback every 10 tokens.

        The callback payload uses ``reasoning=True`` and a placeholder token so
        the UI can show reasoning progress without leaking chain-of-thought text.
        """
        analyzer = _make_streaming_analyzer()
        reasoning_chunk = make_reasoning_chunk("thinking")
        progress_calls, on_progress = _make_progress_recorder()

        # Send 25 reasoning chunks; expect callbacks at count=10 and count=20 only.
        analyzer._collect_stream_chunks([reasoning_chunk] * 25, on_progress)
        assert len(progress_calls) == 2
        for phase, info in progress_calls:
            assert phase == "streaming"
            assert info["reasoning"] is True
            assert info["token"] == "..."
        assert progress_calls[0][1]["count"] == 10
        assert progress_calls[1][1]["count"] == 20

    def test_collect_stream_chunks_no_reasoning_callback_without_progress_fn(self) -> None:
        """Verify reasoning_content is silently skipped when no on_progress callback is set."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        reasoning_chunk = make_reasoning_chunk("thinking")

        # Should not raise even with many reasoning chunks and no callback.
        content, token_count = analyzer._collect_stream_chunks([reasoning_chunk] * 15, None)
        assert content == ""
        assert token_count == 0


class TestCallLlmStreaming:
    """Tests for the public :meth:`SchemaAnalyzer.call_llm_streaming` entry point."""

    def test_call_llm_streaming_invokes_ensure_config_and_fallback(self) -> None:
        """Verify call_llm_streaming() runs _ensure_config then _call_with_fallback.

        The public method delegates to ``_call_with_fallback`` wrapping
        ``_call_llm_streaming_once``; the result of the inner call is returned
        unchanged.
        """
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        ensure_called = False

        def mock_ensure_config() -> None:
            nonlocal ensure_called
            ensure_called = True

        with (
            patch.object(analyzer, "_ensure_config", side_effect=mock_ensure_config),
            patch.object(
                analyzer,
                "_call_llm_streaming_once",
                return_value={"table_name": "users", "columns": []},
            ) as mock_once,
        ):
            result = analyzer.call_llm_streaming([{"role": "user", "content": "hi"}])

        assert ensure_called is True
        assert result == {"table_name": "users", "columns": []}
        # _call_llm_streaming_once is wrapped by _call_with_fallback which calls it
        # with the current model from config.
        mock_once.assert_called_once()
        called_kwargs = mock_once.call_args.kwargs
        assert called_kwargs["model"] == "gemma-4-26b-a4b-it"

    def test_call_llm_streaming_forwards_on_progress_callback(self) -> None:
        """Verify on_progress callback is forwarded to _call_llm_streaming_once."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        captured_progress: list = []

        def on_progress(phase: str, info: dict[str, Any]) -> None:
            captured_progress.append((phase, info))

        with (
            patch.object(analyzer, "_ensure_config"),
            patch.object(analyzer, "_call_llm_streaming_once", return_value={}) as mock_once,
        ):
            analyzer.call_llm_streaming([{"role": "user", "content": "hi"}], on_progress=on_progress)

        # on_progress is forwarded as the second positional arg to _call_llm_streaming_once.
        assert mock_once.call_args.args[1] is on_progress


class TestCallLlmStreamingOnce:
    """Tests for :meth:`SchemaAnalyzer._call_llm_streaming_once` covering the
    streaming request lifecycle, progress callbacks, and exception handling.
    """

    def test_call_llm_streaming_once_raises_runtime_error_when_config_none(self) -> None:
        """Verify _call_llm_streaming_once() raises RuntimeError when _config is None."""
        analyzer = SchemaAnalyzer(config=None)
        with pytest.raises(RuntimeError, match="AIConfig must be initialized before calling LLM"):
            analyzer._call_llm_streaming_once([], None)

    def test_call_llm_streaming_once_returns_parsed_dict(self) -> None:
        """Verify _call_llm_streaming_once() returns the parsed JSON dict on success."""
        analyzer = _make_streaming_analyzer()
        expected = {"table_name": "users", "columns": []}

        with _patch_streaming_chain(analyzer, collect_return=('{"k": 1}', 5), parse_return=expected):
            result = analyzer._call_llm_streaming_once(
                [{"role": "user", "content": "hi"}], None, model="gemma-4-26b-a4b-it"
            )

        assert result is expected

    def test_call_llm_streaming_once_returns_empty_dict_for_empty_content(self) -> None:
        """Verify _call_llm_streaming_once() returns {} when the stream produces no content."""
        analyzer = _make_streaming_analyzer()

        with _patch_streaming_chain(analyzer, collect_return=("", 0), patch_parse_as_mock=True) as mock_parse:
            result = analyzer._call_llm_streaming_once([], None)
            # _parse_json_response should NOT be called for empty content.
            # Call assert_not_called() via the MagicMock class to avoid pylint's
            # no-member false positive (pylint infers mock_parse as dict from
            # the parse_return default value and cannot narrow the yield type
            # of @contextmanager-decorated functions).
            MagicMock.assert_not_called(mock_parse)

        assert not result

    def test_call_llm_streaming_once_invokes_progress_callbacks_in_order(self) -> None:
        """Verify _call_llm_streaming_once() emits connecting, parsing, and done phases."""
        analyzer = _make_streaming_analyzer()
        progress_calls, on_progress = _make_progress_recorder()

        with _patch_streaming_chain(analyzer, collect_return=('{"k": 1}', 7), parse_return={"k": 1}):
            analyzer._call_llm_streaming_once(
                [{"role": "user", "content": "hi"}], on_progress, model="gemma-4-26b-a4b-it"
            )

        phases = [p[0] for p in progress_calls]
        assert phases == ["connecting", "parsing", "done"]
        assert progress_calls[0][1] == {"model": "gemma-4-26b-a4b-it"}
        assert progress_calls[1][1] == {"tokens": 7}
        assert progress_calls[2][1] == {"tokens": 7, "model": "gemma-4-26b-a4b-it"}

    def test_call_llm_streaming_once_uses_config_model_when_model_none(self) -> None:
        """Verify 'connecting' phase uses config.model when no explicit model is provided."""
        analyzer = _make_streaming_analyzer()
        progress_calls, on_progress = _make_progress_recorder()

        with _patch_streaming_chain(analyzer, collect_return=("", 0), patch_parse_as_mock=True):
            analyzer._call_llm_streaming_once([], on_progress, model=None)

        # The connecting phase should report the config model since model=None.
        assert progress_calls[0] == ("connecting", {"model": "gemma-4-26b-a4b-it"})

    def test_call_llm_streaming_once_reraises_api_timeout_error(self) -> None:
        """Verify APITimeoutError is re-raised unchanged (not wrapped in RuntimeError)."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        mock_client = MagicMock()
        timeout_err = APITimeoutError(request=MagicMock())

        with (
            patch("sqlseed_ai.analyzer._streaming.get_openai_client", return_value=mock_client),
            patch.object(analyzer, "_build_llm_kwargs", return_value={}),
            patch.object(
                analyzer,
                "_create_with_reasoning_fallback",
                side_effect=timeout_err,
            ),
            pytest.raises(APITimeoutError),
        ):
            analyzer._call_llm_streaming_once([], None)

    def test_call_llm_streaming_once_reraises_api_connection_error(self) -> None:
        """Verify APIConnectionError is re-raised unchanged (not wrapped in RuntimeError)."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        mock_client = MagicMock()
        conn_err = APIConnectionError(request=MagicMock())

        with (
            patch("sqlseed_ai.analyzer._streaming.get_openai_client", return_value=mock_client),
            patch.object(analyzer, "_build_llm_kwargs", return_value={}),
            patch.object(
                analyzer,
                "_create_with_reasoning_fallback",
                side_effect=conn_err,
            ),
            pytest.raises(APIConnectionError),
        ):
            analyzer._call_llm_streaming_once([], None)

    def test_call_llm_streaming_once_raises_context_overflow_error(self) -> None:
        """Verify errors classified as ContextOverflowError are re-raised as that type.

        A ValueError whose message contains 'context' and 'exceed' is classified
        as ContextOverflowError so the caller can retry with a compact prompt.
        """
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        mock_client = MagicMock()
        overflow_err = ValueError("context length exceed maximum")

        with (
            patch("sqlseed_ai.analyzer._streaming.get_openai_client", return_value=mock_client),
            patch.object(analyzer, "_build_llm_kwargs", return_value={}),
            patch.object(
                analyzer,
                "_create_with_reasoning_fallback",
                side_effect=overflow_err,
            ),
            pytest.raises(ContextOverflowError),
        ):
            analyzer._call_llm_streaming_once([], None)

    def test_call_llm_streaming_once_wraps_other_errors_as_runtime_error(self) -> None:
        """Verify non-timeout, non-overflow errors are wrapped as RuntimeError."""
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        mock_client = MagicMock()
        other_err = OSError("network unreachable")

        with (
            patch("sqlseed_ai.analyzer._streaming.get_openai_client", return_value=mock_client),
            patch.object(analyzer, "_build_llm_kwargs", return_value={}),
            patch.object(
                analyzer,
                "_create_with_reasoning_fallback",
                side_effect=other_err,
            ),
            pytest.raises(RuntimeError, match="LLM API call failed"),
        ):
            analyzer._call_llm_streaming_once([], None)


class TestSendLlmRequestConfigAndToolCalling:
    """Tests for _send_llm_request config guard and successful tool-calling early return."""

    def test_send_llm_request_raises_runtime_error_when_config_none(self) -> None:
        """Verify _send_llm_request() raises RuntimeError when _config is None."""
        analyzer = SchemaAnalyzer(config=None)
        mock_client = MagicMock()
        with pytest.raises(RuntimeError, match="AIConfig must be initialized before this operation"):
            analyzer._send_llm_request(mock_client, {})

    def test_send_llm_request_returns_tool_call_result_for_google_ai_studio(self) -> None:
        """Verify _send_llm_request() returns the tool-call result directly when non-None.

        For the Google AI Studio backend, tool calling is attempted first; if it
        returns a parsed dict, JSON mode is skipped entirely.
        """
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        mock_client = MagicMock()
        tool_result = {"table_name": "users", "columns": []}

        with (
            patch.object(analyzer, "_try_tool_calling", return_value=tool_result) as mock_tool,
            patch.object(analyzer, "_send_with_json_mode") as mock_json,
        ):
            result = analyzer._send_llm_request(mock_client, {"model": "gemma-4-26b-a4b-it"})

        assert result is tool_result
        mock_tool.assert_called_once()
        # JSON mode should NOT be called when tool calling succeeds.
        mock_json.assert_not_called()

    def test_send_with_json_mode_reraises_non_model_fallback_error(self) -> None:
        """Verify _send_with_json_mode() re-raises errors not classified as ModelFallbackError.

        A 500 Internal Server Error is not a parameter-not-supported condition,
        so it must propagate to the caller instead of triggering a text-mode retry.
        """
        config = AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")
        analyzer = SchemaAnalyzer(config=config)

        mock_client = MagicMock()
        server_err = APIError("500 Internal Server Error", request=MagicMock(), body=None)
        mock_client.chat.completions.create.side_effect = server_err

        kwargs: dict[str, Any] = {
            "model": "gemma-4-26b-a4b-it",
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 4096,
            "temperature": 0.3,
        }
        # The 500 error should be re-raised (not retried without response_format).
        with pytest.raises(APIError, match="500 Internal Server Error"):
            analyzer._send_with_json_mode(mock_client, kwargs)
        # Only one call (the failed JSON-mode attempt); no text-mode retry.
        assert mock_client.chat.completions.create.call_count == 1
