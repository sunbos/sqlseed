"""Availability probes distinguish an offline service from a broken test setup."""

from __future__ import annotations

import importlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from .conftest import fixture_llm_available

pytest.importorskip("sqlseed_ai")
httpx = importlib.import_module("httpx")
MODEL = "google/gemma-4-e2b"


def _response(**kwargs: object) -> httpx.Response:
    return httpx.Response(200, request=httpx.Request("GET", "http://localhost:1234/v1/models"), **kwargs)


@pytest.mark.parametrize("status", [401, 403, 404, 500, 503])
def test_http_failures_do_not_skip_acceptance(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    response = httpx.Response(status, request=httpx.Request("GET", "http://localhost:1234/v1/models"))
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: response)

    with pytest.raises(httpx.HTTPStatusError):
        fixture_llm_available.__wrapped__(MODEL)


@pytest.mark.parametrize(
    ("models", "available"),
    [([], False), ([{"id": "another-model"}], False), ([{"id": "another-model"}, {"id": MODEL}], True)],
)
def test_availability_requires_requested_model(
    monkeypatch: pytest.MonkeyPatch, models: list[dict[str, str]], available: bool
) -> None:
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: _response(json={"data": models}))

    assert fixture_llm_available.__wrapped__(MODEL) is available


@pytest.mark.parametrize("payload", [[], {}, {"data": None}, {"data": [None]}, {"data": [{}]}, {"data": [{"id": 1}]}])
def test_malformed_model_list_fails_setup(monkeypatch: pytest.MonkeyPatch, payload: object) -> None:
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: _response(json=payload))

    with pytest.raises(ValueError, match="LM Studio model"):
        fixture_llm_available.__wrapped__(MODEL)


def test_invalid_model_list_json_fails_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: _response(content=b"not json"))

    with pytest.raises(ValueError):
        fixture_llm_available.__wrapped__(MODEL)


def test_unreachable_service_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def unreachable(*args: object, **kwargs: object) -> None:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", unreachable)

    assert fixture_llm_available.__wrapped__(MODEL) is False


@pytest.mark.parametrize("error", [ValueError("invalid request setup"), RuntimeError("broken probe")])
def test_probe_errors_do_not_skip_real_llm_tests(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def broken_probe(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(httpx, "get", broken_probe)

    with pytest.raises(type(error)) as caught:
        fixture_llm_available.__wrapped__(MODEL)
    assert caught.value is error


def test_local_probe_bypasses_environment_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real loopback model-list endpoint must not be sent through an unrelated proxy."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"data": [{"id": "google/gemma-4-e2b"}]}')

        def log_message(self, *args: object) -> None:
            pass

    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    actual_get = httpx.get
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        server_thread = Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        url = f"http://127.0.0.1:{server.server_port}/v1/models"
        monkeypatch.setattr(httpx, "get", lambda _url, **kwargs: actual_get(url, **kwargs))
        try:
            assert fixture_llm_available.__wrapped__(MODEL) is True
        finally:
            server.shutdown()
            server_thread.join(timeout=5)
