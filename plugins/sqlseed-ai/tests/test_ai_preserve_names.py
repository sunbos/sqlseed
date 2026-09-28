"""Protocol-level identifier fidelity; fixed HTTP responses are not model acceptance."""

from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

pytest.importorskip("sqlseed_ai")

import httpx
from openai import OpenAI
from sqlseed_ai import AIBackend, AIConfig, SchemaAnalyzer
from sqlseed_ai._json_utils import JSONResponseError, parse_json_response

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
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if "response_format" in body:
            return httpx.Response(400, json={"error": {"message": "response_format is not supported"}})
        return _completion({"content": f"Configuration:\n{_JSON}"})

    kwargs = {"preserve_names": True} if preserve_names else {}
    with _analyzer_http(monkeypatch, handle) as analyzer:
        result = analyzer.call_llm(_MESSAGES, strict_json=True, **kwargs)
    assert result == _expected(preserved=preserve_names)
    assert len(requests) == 2
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in requests[1]


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
