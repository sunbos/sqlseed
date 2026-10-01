"""Protocol-level identifier fidelity; fixed HTTP responses are not model acceptance."""

from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from typing import TYPE_CHECKING, Any

import pytest

try:
    from sqlseed_ai import AIBackend, AIConfig, SchemaAnalyzer
    from sqlseed_ai._json_utils import JSONResponseError, parse_json_response
except ModuleNotFoundError as exc:
    if exc.name != "sqlseed_ai":
        raise
    pytest.skip("sqlseed-ai is not installed", allow_module_level=True)

import httpx
from openai import OpenAI

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

_CONFIG = {
    "name": ".events",
    "columns": [
        {"name": ".value", "generator": "integer", "params": {"min_value": 7, "max_value": 7}},
        {"name": ":status", "generator": "choice", "params": {"choices": [".ready", ":pending"]}},
    ],
}
_JSON = json.dumps(_CONFIG)
_MESSAGES = [{"role": "user", "content": 'Return rules for table ".events".'}]
_RESPONSES = [
    pytest.param(_JSON, id="raw"),
    pytest.param(f"```json\n{_JSON}\n```", id="fenced"),
    pytest.param(f"Here is the configuration:\n{_JSON}\nEnd of answer.", id="prose"),
    pytest.param(_JSON[:-2], id="missing-array-and-object-closers"),
    pytest.param(f"```json\n{_JSON[:-2]}\n```", id="fenced-missing-closers"),
    pytest.param(f"<|channel>thought\nIgnore {{3}} in reasoning.\n<channel|>{_JSON}", id="channel"),
]


def _expected(*, preserved: bool) -> dict[str, Any]:
    result = deepcopy(_CONFIG)
    if not preserved:
        result["name"] = "events"
        result["columns"][0]["name"] = "value"
        result["columns"][1]["name"] = "status"
    return result


@pytest.mark.parametrize("content", _RESPONSES)
@pytest.mark.parametrize("strict", [False, True])
def test_parser_can_preserve_identifiers_without_changing_default_recovery(content: str, strict: bool) -> None:
    assert parse_json_response(content, strict=strict, preserve_names=True) == _expected(preserved=True)
    assert parse_json_response(content, strict=strict) == _expected(preserved=False)


@pytest.mark.parametrize(
    "content,code",
    [
        (" ", "empty_response"),
        ('{"name": ".unfinished', "invalid_json"),
        ('{"name": ".events", "columns": [}', "invalid_json"),
        ('{"name": ".events", "columns":', "invalid_json"),
    ],
)
@pytest.mark.parametrize("preserve_names", [False, True])
def test_name_preservation_never_invents_missing_values_or_weakens_strict_errors(
    content: str, code: str, preserve_names: bool
) -> None:
    with pytest.raises(JSONResponseError) as captured:
        parse_json_response(content, strict=True, preserve_names=preserve_names)
    assert captured.value.code == code
    assert str(captured.value) == code
    assert parse_json_response(content, preserve_names=preserve_names) == {}


@contextmanager
def _analyzer_http(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    tools: bool = False,
) -> Iterator[SchemaAnalyzer]:
    """Keep SDK decoding, dispatch and parsing real; replace only the HTTP peer."""
    with OpenAI(
        api_key="protocol-test-key",
        base_url="http://protocol.invalid/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
    ) as client:
        monkeypatch.setattr("sqlseed_ai.analyzer._caller.get_openai_client", lambda _config: client)
        monkeypatch.setattr("sqlseed_ai.analyzer._streaming.get_openai_client", lambda _config: client)
        yield SchemaAnalyzer(
            AIConfig(
                backend=AIBackend.OPENAI_COMPAT,
                base_url="http://protocol.invalid/v1",
                api_key="protocol-test-key",
                model="identifier-protocol-test",
                tool_calling_protocol="openai" if tools else "none",
                log_llm_interactions=False,
            )
        )


def _completion(message: dict[str, Any], *, finish_reason: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "identifier-fidelity",
            "object": "chat.completion",
            "created": 0,
            "model": "identifier-protocol-test",
            "choices": [{"index": 0, "message": {"role": "assistant", **message}, "finish_reason": finish_reason}],
        },
    )


def _sse(content: str) -> httpx.Response:
    # Break the table and column names across chunks to exercise real collection.
    chunks = []
    for offset in range(0, len(content), 5):
        chunk = {
            "id": "identifier-fidelity",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "identifier-protocol-test",
            "choices": [{"index": 0, "delta": {"content": content[offset : offset + 5]}, "finish_reason": None}],
        }
        chunks.append(f"data: {json.dumps(chunk)}\n\n")
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content="".join(chunks) + "data: [DONE]\n\n",
    )


def _tool_message() -> dict[str, Any]:
    return {
        "content": None,
        "tool_calls": [
            {
                "id": "schema-analysis",
                "type": "function",
                "function": {"name": "analyze_schema", "arguments": _JSON},
            }
        ],
    }


def _unsupported_format_handler(
    requests: list[dict[str, Any]], text_response: httpx.Response
) -> Callable[[httpx.Request], httpx.Response]:
    """Record attempts and reject format negotiation before returning the text reply."""

    def handle(request: httpx.Request) -> httpx.Response:
        """Record both negotiation attempts and reject only requests that specify a response format."""
        body = json.loads(request.content)
        requests.append(body)
        if "response_format" in body:
            return httpx.Response(400, json={"error": {"message": "response_format is not supported"}})
        return text_response

    return handle


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("preserve_names", [False, True])
def test_analyzer_http_and_sse_paths_preserve_names_only_when_requested(
    monkeypatch: pytest.MonkeyPatch, streaming: bool, preserve_names: bool
) -> None:
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return _sse(f"```json\n{_JSON}\n```") if streaming else _completion({"content": _JSON})

    kwargs = {"preserve_names": True} if preserve_names else {}
    with _analyzer_http(monkeypatch, handle) as analyzer:
        call = analyzer.call_llm_streaming if streaming else analyzer.call_llm
        result = call(_MESSAGES, **kwargs)
    assert result == _expected(preserved=preserve_names)
    assert len(requests) == 1
    assert requests[0]["messages"] == _MESSAGES
    assert bool(requests[0].get("stream")) is streaming
    assert "preserve_names" not in requests[0]


@pytest.mark.parametrize("preserve_names", [False, True])
def test_json_mode_fallback_keeps_requested_name_policy(monkeypatch: pytest.MonkeyPatch, preserve_names: bool) -> None:
    """Preserve the caller's identifier policy when JSON mode falls back to plain text."""
    requests = []
    handle = _unsupported_format_handler(requests, _completion({"content": f"Configuration:\n{_JSON}"}))
    kwargs = {"preserve_names": True} if preserve_names else {}
    with _analyzer_http(monkeypatch, handle) as analyzer:
        result = analyzer.call_llm(_MESSAGES, strict_json=True, **kwargs)
    assert result == _expected(preserved=preserve_names)
    assert len(requests) == 2
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in requests[1]


@pytest.mark.parametrize("backend", [AIBackend.LM_STUDIO, AIBackend.OLLAMA])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("strict", [False, True])
def test_local_json_sampling_preserves_identifiers_and_optional_text_mode(
    monkeypatch: pytest.MonkeyPatch, backend: AIBackend, streaming: bool, strict: bool
) -> None:
    """Check backend-specific strict formats while keeping legacy text mode and names intact."""
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        """Capture the wire format and return identical content through JSON or SSE transport."""
        requests.append(json.loads(request.content))
        return _sse(_JSON) if streaming else _completion({"content": _JSON})

    with _analyzer_http(monkeypatch, handle) as analyzer:
        assert analyzer.config is not None
        analyzer.config.backend = backend
        call = analyzer.call_llm_streaming if streaming else analyzer.call_llm
        result = call(_MESSAGES, strict_json=strict, preserve_names=True)

    assert result == _CONFIG
    assert len(requests) == 1
    assert requests[0]["messages"] == _MESSAGES
    assert bool(requests[0].get("stream")) is streaming
    if not strict:
        assert "response_format" not in requests[0]
    elif backend == AIBackend.LM_STUDIO:
        assert requests[0]["response_format"] == {
            "type": "json_schema",
            "json_schema": {"name": "json_object_response", "strict": True, "schema": {"type": "object"}},
        }
    else:
        assert requests[0]["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("backend", [AIBackend.LM_STUDIO, AIBackend.OLLAMA])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("content", [_JSON, '{"name":".events","columns":INVALID}'])
def test_unsupported_local_format_falls_back_once_and_keeps_strict_parsing(
    monkeypatch: pytest.MonkeyPatch, backend: AIBackend, streaming: bool, content: str
) -> None:
    """Allow one format fallback without changing request budgets or accepting invalid JSON."""
    requests = []
    handle = _unsupported_format_handler(requests, _sse(content) if streaming else _completion({"content": content}))

    with _analyzer_http(monkeypatch, handle) as analyzer:
        assert analyzer.config is not None
        analyzer.config.backend = backend
        call = analyzer.call_llm_streaming if streaming else analyzer.call_llm
        if content == _JSON:
            assert call(_MESSAGES, strict_json=True, preserve_names=True) == _CONFIG
        else:
            with pytest.raises(JSONResponseError) as error:
                call(_MESSAGES, strict_json=True, preserve_names=True)
            assert error.value.code == "invalid_json"

    assert len(requests) == 2
    assert "response_format" in requests[0]
    assert "response_format" not in requests[1]
    for key in ("model", "messages", "max_tokens", "temperature", "stream"):
        assert requests[0].get(key) == requests[1].get(key)


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    "status,message",
    [
        (401, "Authentication required"),
        (401, "response_format is not supported for this unauthorized request"),
        (400, "Invalid max_tokens; 400 Bad Request"),
        (500, "response_format is unsupported due to an internal error"),
    ],
)
def test_local_json_sampling_does_not_retry_unrelated_service_failures(
    monkeypatch: pytest.MonkeyPatch, streaming: bool, status: int, message: str
) -> None:
    """Keep authentication, argument and server errors outside format-compatibility retries."""
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        """Return the specified service error while recording whether an extra request occurs."""
        requests.append(json.loads(request.content))
        return httpx.Response(status, json={"error": {"message": message}})

    with _analyzer_http(monkeypatch, handle) as analyzer:
        assert analyzer.config is not None
        analyzer.config.backend = AIBackend.LM_STUDIO
        call = analyzer.call_llm_streaming if streaming else analyzer.call_llm
        with pytest.raises(RuntimeError, match=message):
            call(_MESSAGES, strict_json=True, preserve_names=True)

    assert len(requests) == 1
    assert requests[0]["response_format"]["type"] == "json_schema"


@pytest.mark.parametrize("preserve_names", [False, True])
def test_strict_completion_rejects_output_limit_even_if_json_is_complete(
    monkeypatch: pytest.MonkeyPatch, preserve_names: bool
) -> None:
    with (
        _analyzer_http(
            monkeypatch, lambda _request: _completion({"content": _JSON}, finish_reason="length")
        ) as analyzer,
        pytest.raises(JSONResponseError) as captured,
    ):
        analyzer.call_llm(_MESSAGES, strict_json=True, preserve_names=preserve_names)
    assert captured.value.code == "truncated_response"


@pytest.mark.parametrize("tool_arguments", [False, True])
@pytest.mark.parametrize("preserve_names", [False, True])
def test_tool_protocol_arguments_and_content_fallback_reach_real_parser(
    monkeypatch: pytest.MonkeyPatch, tool_arguments: bool, preserve_names: bool
) -> None:
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if not tool_arguments:
            return _completion({"content": f"```json\n{_JSON}\n```"})
        return _completion(_tool_message(), finish_reason="tool_calls")

    kwargs = {"preserve_names": True} if preserve_names else {}
    with _analyzer_http(monkeypatch, handle, tools=True) as analyzer:
        result = analyzer.call_llm(_MESSAGES, **kwargs)
    # Structured tool arguments were already preserved before this opt-in flag.
    assert result == _expected(preserved=tool_arguments or preserve_names)
    assert len(requests) == 1
    assert requests[0]["tools"]
    assert requests[0]["tool_choice"] == "auto"


@pytest.mark.parametrize("tool_arguments", [False, True])
@pytest.mark.parametrize("preserve_names", [False, True])
def test_strict_tool_protocol_rejects_output_limit_before_returning_parsed_dict(
    monkeypatch: pytest.MonkeyPatch, tool_arguments: bool, preserve_names: bool
) -> None:
    message = _tool_message() if tool_arguments else {"content": _JSON}
    with (
        _analyzer_http(
            monkeypatch, lambda _request: _completion(message, finish_reason="length"), tools=True
        ) as analyzer,
        pytest.raises(JSONResponseError) as captured,
    ):
        analyzer.call_llm(_MESSAGES, strict_json=True, preserve_names=preserve_names)
    assert captured.value.code == "truncated_response"
    assert str(captured.value) == "truncated_response"


@pytest.mark.parametrize(
    "content,code",
    [(None, "empty_response"), ("", "empty_response"), (" ", "empty_response"), ("PRIVATE invalid", "invalid_json")],
)
@pytest.mark.parametrize("preserve_names", [False, True])
def test_strict_tool_text_fallback_does_not_hide_empty_or_invalid_response(
    monkeypatch: pytest.MonkeyPatch, content: str | None, code: str, preserve_names: bool
) -> None:
    with (
        _analyzer_http(monkeypatch, lambda _request: _completion({"content": content}), tools=True) as analyzer,
        pytest.raises(JSONResponseError) as captured,
    ):
        analyzer.call_llm(_MESSAGES, strict_json=True, preserve_names=preserve_names)
    assert captured.value.code == code
    assert str(captured.value) == code


@pytest.mark.parametrize("arguments", ["[]", '[{"name":"events"}]', "17", '"PRIVATE_RESPONSE_MARKER"', "null", "true"])
def test_strict_tool_arguments_require_an_object_without_retrying(
    monkeypatch: pytest.MonkeyPatch, arguments: str
) -> None:
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        message = _tool_message()
        message["tool_calls"][0]["function"]["arguments"] = arguments
        return _completion(message, finish_reason="tool_calls")

    with (
        _analyzer_http(monkeypatch, handle, tools=True) as analyzer,
        pytest.raises(JSONResponseError) as captured,
    ):
        analyzer.call_llm(_MESSAGES, strict_json=True, preserve_names=True)

    assert captured.value.code == "invalid_json"
    assert str(captured.value) == "invalid_json"
    assert len(requests) == 1


@pytest.mark.parametrize("preserve_names", [False, True])
def test_legacy_tool_arguments_can_fall_back_to_valid_text(
    monkeypatch: pytest.MonkeyPatch, preserve_names: bool
) -> None:
    message = _tool_message()
    message["tool_calls"][0]["function"]["arguments"] = "[]"
    message["content"] = _JSON
    with _analyzer_http(monkeypatch, lambda _request: _completion(message), tools=True) as analyzer:
        result = analyzer.call_llm(_MESSAGES, preserve_names=preserve_names)
    assert result == _expected(preserved=preserve_names)


@pytest.mark.parametrize(
    "calls,expected,strict_error",
    [
        pytest.param(
            [
                ("unrelated", "[]"),
                ("analyze_schema", ""),
                ("analyze_schema", "malformed JSON"),
                ("analyze_schema", _JSON),
                ("analyze_schema", '{"name":"later"}'),
            ],
            _CONFIG,
            False,
            id="skip-unrelated-empty-and-malformed-before-first-object",
        ),
        pytest.param(
            [("analyze_schema", "{}"), ("analyze_schema", _JSON)],
            {},
            False,
            id="empty-object-still-wins",
        ),
        pytest.param(
            [("analyze_schema", "[]"), ("analyze_schema", _JSON)],
            _CONFIG,
            True,
            id="nonobject-before-object-rejected-only-in-strict-mode",
        ),
    ],
)
@pytest.mark.parametrize("strict", [False, True])
def test_tool_response_order_keeps_first_object_and_strict_failures(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[tuple[str, str]],
    expected: dict[str, Any],
    strict_error: bool,
    strict: bool,
) -> None:
    """Decode real SDK tool messages; neither later tools nor text replace a result."""
    requests = []
    message = {
        "content": '{"name":"text-fallback"}',
        "tool_calls": [
            {"id": f"tool-{index}", "type": "function", "function": {"name": name, "arguments": arguments}}
            for index, (name, arguments) in enumerate(calls)
        ],
    }

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return _completion(message, finish_reason="tool_calls")

    with _analyzer_http(monkeypatch, handle, tools=True) as analyzer:
        if strict and strict_error:
            with pytest.raises(JSONResponseError) as captured:
                analyzer.call_llm(_MESSAGES, strict_json=True, preserve_names=True)
            assert captured.value.code == "invalid_json"
        else:
            assert analyzer.call_llm(_MESSAGES, strict_json=strict, preserve_names=True) == expected
    assert len(requests) == 1
