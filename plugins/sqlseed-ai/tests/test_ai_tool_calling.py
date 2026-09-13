"""Tests for the ToolCallingMixin in sqlseed_ai.analyzer._tool_calling.

Covers ``_try_tool_calling``: successful tool call extraction, content
fallback when no tool call is made, empty/missing choices handling, the
``response_format`` removal for tool kwargs, and exception classification
(``ToolCallError`` fallback to JSON mode vs. re-raise of other errors).
All LLM clients are mocked — no real API requests are made.
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


def _make_config() -> AIConfig:
    """Build a minimal AIConfig for Google AI Studio (tool-calling eligible)."""
    return AIConfig(backend=AIBackend.GOOGLE_AI_STUDIO, model="gemma-4-26b-a4b-it")


def _make_tool_call(name: str, arguments: str) -> Any:
    """Build a mock tool_call with the given function name and arguments string."""
    tc = MagicMock()
    tc.function.name = name
    tc.function.arguments = arguments
    return tc


def _make_choice(tool_calls: Any = None, content: Any = None) -> Any:
    """Build a mock choice with the given tool_calls list and message content."""
    choice = MagicMock()
    choice.message.tool_calls = tool_calls
    choice.message.content = content
    return choice


def _make_response(choices: list[Any]) -> Any:
    """Build a mock response with the given choices list."""
    resp = MagicMock()
    resp.choices = choices
    return resp


# ── Successful tool call extraction ──────────────────────────────────


class TestTryToolCallingSuccess:
    def test_returns_parsed_tool_call_result(self) -> None:
        """_try_tool_calling returns the parsed args dict from analyze_schema."""
        analyzer = SchemaAnalyzer(config=_make_config())

        tool_call = _make_tool_call("analyze_schema", '{"table_name": "users", "columns": []}')
        choice = _make_choice(tool_calls=[tool_call])
        response = _make_response([choice])

        client = MagicMock()
        client.chat.completions.create.return_value = response

        result = analyzer._try_tool_calling(client, {"model": "gemma-4-26b-a4b-it"})
        assert isinstance(result, dict)
        assert result == {"table_name": "users", "columns": []}

    def test_response_format_removed_from_tool_kwargs(self) -> None:
        """_try_tool_calling strips response_format and injects tools/tool_choice."""
        analyzer = SchemaAnalyzer(config=_make_config())

        tool_call = _make_tool_call("analyze_schema", '{"table_name": "users"}')
        choice = _make_choice(tool_calls=[tool_call])
        response = _make_response([choice])

        client = MagicMock()
        client.chat.completions.create.return_value = response

        kwargs: dict[str, Any] = {
            "model": "test",
            "response_format": {"type": "json_object"},
        }
        analyzer._try_tool_calling(client, kwargs)

        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert "response_format" not in call_kwargs
        assert call_kwargs["tools"] is not None
        assert call_kwargs["tool_choice"] == "auto"

    def test_first_analyze_schema_call_wins(self) -> None:
        """_try_tool_calling returns the first analyze_schema call's parsed args."""
        analyzer = SchemaAnalyzer(config=_make_config())

        first = _make_tool_call("analyze_schema", '{"table_name": "first"}')
        second = _make_tool_call("analyze_schema", '{"table_name": "second"}')
        choice = _make_choice(tool_calls=[first, second])
        response = _make_response([choice])

        client = MagicMock()
        client.chat.completions.create.return_value = response

        result = analyzer._try_tool_calling(client, {"model": "test"})
        assert isinstance(result, dict)
        assert result == {"table_name": "first"}


# ── Empty / missing choices ──────────────────────────────────────────


class TestTryToolCallingNoChoices:
    def test_returns_none_when_no_choices(self) -> None:
        """_try_tool_calling returns None when the response has no choices."""
        analyzer = SchemaAnalyzer(config=_make_config())

        response = _make_response([])
        client = MagicMock()
        client.chat.completions.create.return_value = response

        assert analyzer._try_tool_calling(client, {"model": "test"}) is None


# ── Content fallback when no tool call is made ───────────────────────


def _run_content_fallback(
    analyzer: SchemaAnalyzer, choice: Any, *, expected_parse_call: str | None = None
) -> dict[str, Any]:
    """Run _try_tool_calling with a client returning ``choice``, expect content fallback.

    Builds a mock client whose ``chat.completions.create`` returns a response
    containing the given choice, patches ``_parse_json_response`` to return
    ``{"name": "fallback"}``, and asserts the result equals that dict.

    If ``expected_parse_call`` is provided, also asserts ``_parse_json_response``
    was called once with that string.
    """
    response = _make_response([choice])
    client = MagicMock()
    client.chat.completions.create.return_value = response

    with patch.object(analyzer, "_parse_json_response", return_value={"name": "fallback"}) as mock_parse:
        result = analyzer._try_tool_calling(client, {"model": "test"})
        assert isinstance(result, dict)
        assert result == {"name": "fallback"}
        if expected_parse_call is not None:
            mock_parse.assert_called_once_with(expected_parse_call)
    return result


class TestTryToolCallingContentFallback:
    def test_falls_back_to_parse_json_response_when_content_present(self) -> None:
        """_try_tool_calling parses message content via _parse_json_response."""
        analyzer = SchemaAnalyzer(config=_make_config())

        choice = _make_choice(tool_calls=None, content='{"name": "users"}')
        response = _make_response([choice])

        client = MagicMock()
        client.chat.completions.create.return_value = response

        with patch.object(analyzer, "_parse_json_response", return_value={"name": "users"}) as mock_parse:
            result = analyzer._try_tool_calling(client, {"model": "test"})
            assert isinstance(result, dict)
            assert result == {"name": "users"}
            mock_parse.assert_called_once_with('{"name": "users"}')

    def test_returns_none_when_no_tool_calls_and_no_content(self) -> None:
        """_try_tool_calling returns None when no tool calls and empty content."""
        analyzer = SchemaAnalyzer(config=_make_config())

        choice = _make_choice(tool_calls=None, content=None)
        response = _make_response([choice])

        client = MagicMock()
        client.chat.completions.create.return_value = response

        assert analyzer._try_tool_calling(client, {"model": "test"}) is None

    def test_returns_none_when_tool_call_wrong_function_and_no_content(self) -> None:
        """_try_tool_calling returns None for non-analyze_schema tool calls."""
        analyzer = SchemaAnalyzer(config=_make_config())

        wrong_tc = _make_tool_call("other_function", '{"foo": "bar"}')
        choice = _make_choice(tool_calls=[wrong_tc], content=None)
        response = _make_response([choice])

        client = MagicMock()
        client.chat.completions.create.return_value = response

        assert analyzer._try_tool_calling(client, {"model": "test"}) is None

    def test_wrong_function_then_content_fallback(self) -> None:
        """_try_tool_calling falls back to content when tool call name is wrong."""
        analyzer = SchemaAnalyzer(config=_make_config())
        wrong_tc = _make_tool_call("other_function", '{"foo": "bar"}')
        choice = _make_choice(tool_calls=[wrong_tc], content='{"name": "fallback"}')
        _run_content_fallback(analyzer, choice, expected_parse_call='{"name": "fallback"}')

    def test_invalid_json_args_skipped_then_content_fallback(self) -> None:
        """_try_tool_calling skips invalid JSON args and falls back to content."""
        analyzer = SchemaAnalyzer(config=_make_config())
        bad_tc = _make_tool_call("analyze_schema", "not valid json {{{")
        choice = _make_choice(tool_calls=[bad_tc], content='{"name": "fallback"}')
        _run_content_fallback(analyzer, choice, expected_parse_call='{"name": "fallback"}')

    def test_empty_arguments_skipped_then_content_fallback(self) -> None:
        """_try_tool_calling skips analyze_schema calls with empty arguments."""
        analyzer = SchemaAnalyzer(config=_make_config())
        empty_args_tc = _make_tool_call("analyze_schema", "")
        choice = _make_choice(tool_calls=[empty_args_tc], content='{"name": "fallback"}')
        _run_content_fallback(analyzer, choice)

    def test_empty_tool_calls_list_falls_back_to_content(self) -> None:
        """_try_tool_calling treats an empty tool_calls list as no tool calls."""
        analyzer = SchemaAnalyzer(config=_make_config())
        choice = _make_choice(tool_calls=[], content='{"name": "fallback"}')
        _run_content_fallback(analyzer, choice)


# ── Exception handling: fallback vs. re-raise ────────────────────────


class TestTryToolCallingExceptionHandling:
    def test_returns_none_on_api_error_with_tool_message(self) -> None:
        """APIError containing 'tool' is classified as ToolCallError -> None."""
        analyzer = SchemaAnalyzer(config=_make_config())

        client = MagicMock()
        client.chat.completions.create.side_effect = APIError(
            "tool calling not supported", request=MagicMock(), body=None
        )

        assert analyzer._try_tool_calling(client, {"model": "test"}) is None

    def test_returns_none_on_api_error_with_function_message(self) -> None:
        """APIError containing 'function' is classified as ToolCallError -> None."""
        analyzer = SchemaAnalyzer(config=_make_config())

        client = MagicMock()
        client.chat.completions.create.side_effect = APIError(
            "function calling not supported", request=MagicMock(), body=None
        )

        assert analyzer._try_tool_calling(client, {"model": "test"}) is None

    def test_reraises_unclassified_api_error(self) -> None:
        """APIError that does not classify as ToolCallError is re-raised."""
        analyzer = SchemaAnalyzer(config=_make_config())

        client = MagicMock()
        # "context length exceeded" classifies as ContextOverflowError, not ToolCallError
        client.chat.completions.create.side_effect = APIError("context length exceeded", request=MagicMock(), body=None)

        with pytest.raises(APIError):
            analyzer._try_tool_calling(client, {"model": "test"})

    def test_returns_none_on_value_error_with_tool_message(self) -> None:
        """ValueError containing 'tool' is classified as ToolCallError -> None."""
        analyzer = SchemaAnalyzer(config=_make_config())

        client = MagicMock()
        client.chat.completions.create.side_effect = ValueError("tool not supported")

        assert analyzer._try_tool_calling(client, {"model": "test"}) is None

    def test_reraises_unclassified_value_error(self) -> None:
        """ValueError that does not classify as ToolCallError is re-raised."""
        analyzer = SchemaAnalyzer(config=_make_config())

        client = MagicMock()
        client.chat.completions.create.side_effect = ValueError("some other error")

        with pytest.raises(ValueError, match="some other error"):
            analyzer._try_tool_calling(client, {"model": "test"})

    def test_returns_none_on_runtime_error_with_function_message(self) -> None:
        """RuntimeError containing 'function' is classified as ToolCallError -> None."""
        analyzer = SchemaAnalyzer(config=_make_config())

        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("function call failed")

        assert analyzer._try_tool_calling(client, {"model": "test"}) is None

    def test_reraises_unclassified_runtime_error(self) -> None:
        """RuntimeError that does not classify as ToolCallError is re-raised."""
        analyzer = SchemaAnalyzer(config=_make_config())

        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("unexpected failure")

        with pytest.raises(RuntimeError, match="unexpected failure"):
            analyzer._try_tool_calling(client, {"model": "test"})

    def test_uses_config_model_in_log_when_config_present(self) -> None:
        """_try_tool_calling does not crash when self._config is set (logging path)."""
        config = _make_config()
        analyzer = SchemaAnalyzer(config=config)

        client = MagicMock()
        client.chat.completions.create.side_effect = ValueError("tool unsupported")

        # Should return None without raising — the log message references config.model
        assert analyzer._try_tool_calling(client, {"model": "kwarg-model"}) is None

    def test_uses_kwargs_model_when_config_absent(self) -> None:
        """_try_tool_calling falls back to kwargs model when config is None."""
        analyzer = SchemaAnalyzer(config=None)

        client = MagicMock()
        client.chat.completions.create.side_effect = ValueError("tool unsupported")

        assert analyzer._try_tool_calling(client, {"model": "kwarg-model"}) is None
