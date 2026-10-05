"""Analyzer requests own and close their real SDK clients on every exit path."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

pytest.importorskip("sqlseed_ai")

from openai import OpenAI
from sqlseed_ai._json_utils import JSONResponseError
from sqlseed_ai.analyzer import SchemaAnalyzer
from sqlseed_ai.config import AIBackend, AIConfig


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("outcome", ["success", "invalid_json", "http_error"])
def test_analyzer_closes_owned_sdk_client(monkeypatch: pytest.MonkeyPatch, streaming: bool, outcome: str) -> None:
    """Exercise real SDK response parsing and HTTP-client closure, with only the peer replaced."""
    content = '{"name":"items","columns":[]}' if outcome == "success" else "invalid JSON"

    def respond(request: httpx.Request) -> httpx.Response:
        if outcome == "http_error":
            return httpx.Response(503, json={"error": {"message": "service unavailable"}})
        choice: dict[str, Any] = {"index": 0, "finish_reason": "stop"}
        choice["delta" if streaming else "message"] = {"role": "assistant", "content": content}
        payload = {"id": "lifecycle", "created": 0, "model": "test-model", "choices": [choice]}
        if streaming:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n",
            )
        return httpx.Response(200, json=payload)

    client = OpenAI(
        api_key="test-key",
        base_url="http://lifecycle.invalid/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
        max_retries=0,
    )
    monkeypatch.setattr("sqlseed_ai.analyzer._caller.get_openai_client", lambda config: client)
    monkeypatch.setattr("sqlseed_ai.analyzer._streaming.get_openai_client", lambda config: client)
    analyzer = SchemaAnalyzer(
        AIConfig(
            backend=AIBackend.OPENAI_COMPAT,
            model="test-model",
            tool_calling_protocol="none",
            log_llm_interactions=False,
        )
    )

    def call() -> dict[str, Any]:
        if streaming:
            return analyzer._call_llm_streaming_once([], None, strict_json=True)
        return analyzer._call_llm_once([], strict_json=True)

    try:
        if outcome == "success":
            assert call()["name"] == "items"
        else:
            with pytest.raises(JSONResponseError if outcome == "invalid_json" else RuntimeError):
                call()
        assert client.is_closed()
    finally:
        client.close()


def test_streaming_connecting_callback_failure_closes_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """The first progress callback runs after client creation and can fail before any request."""
    client = OpenAI(api_key="test-key", base_url="http://lifecycle.invalid/v1")
    monkeypatch.setattr("sqlseed_ai.analyzer._streaming.get_openai_client", lambda config: client)
    analyzer = SchemaAnalyzer(AIConfig(model="test-model", log_llm_interactions=False))

    def fail_progress(stage: str, details: dict[str, Any]) -> None:
        raise RuntimeError("progress callback failed")

    try:
        with pytest.raises(RuntimeError, match="progress callback failed"):
            analyzer._call_llm_streaming_once([], on_progress=fail_progress)
        assert client.is_closed()
    finally:
        client.close()


def test_streaming_callback_interruption_closes_unconsumed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """A callback can interrupt an SSE body before EOF; client closure alone is insufficient."""
    chunk = {"choices": [{"index": 0, "delta": {"content": "x"}, "finish_reason": None}]}

    class ChunkStream(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(20):
                yield f"data: {json.dumps(chunk)}\n\n".encode()

    response = httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=ChunkStream())
    client = OpenAI(
        api_key="test-key",
        base_url="http://lifecycle.invalid/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(lambda request: response)),
    )
    monkeypatch.setattr("sqlseed_ai.analyzer._streaming.get_openai_client", lambda config: client)
    analyzer = SchemaAnalyzer(AIConfig(model="test-model", log_llm_interactions=False))

    def fail_during_stream(stage: str, details: dict[str, Any]) -> None:
        if stage == "streaming":
            raise RuntimeError("stream callback failed")

    try:
        with pytest.raises(RuntimeError, match="stream callback failed"):
            analyzer._call_llm_streaming_once([], on_progress=fail_during_stream)
        assert response.is_closed
        assert client.is_closed()
    finally:
        response.close()
        client.close()
