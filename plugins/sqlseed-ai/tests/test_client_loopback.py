"""Real HTTP routing checks for AI clients; fixed responses do not certify a model."""

from __future__ import annotations

import json
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

try:
    from sqlseed_ai._client import build_openai_client, get_openai_client
    from sqlseed_ai.config import AIBackend, AIConfig
    from sqlseed_ai.runtime import build_llm_client
except ModuleNotFoundError as exc:
    if exc.name != "sqlseed_ai":
        raise
    pytest.skip("sqlseed-ai plugin not installed", allow_module_level=True)


@pytest.fixture(name="completion_server")
def fixture_completion_server() -> Iterator[tuple[int, list[str]]]:
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            requests.append(self.path)
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path.startswith("/redirect/"):
                self.send_response(307)
                self.send_header("Location", "http://remote.invalid/v1/chat/completions")
                self.end_headers()
                return
            result = {
                "id": "loopback-protocol-test",
                "created": 0,
                "object": "chat.completion",
                "model": payload["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "local reply"}}],
            }
            body = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield server.server_port, requests
        finally:
            server.shutdown()
            worker.join(timeout=5)


def _use_proxy(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, url)
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")


@pytest.mark.parametrize("factory", ["analyzer", "runtime"])
@pytest.mark.parametrize("hostname", ["localhost", "127.0.0.1"])
def test_loopback_completion_bypasses_proxy(
    monkeypatch: pytest.MonkeyPatch, completion_server: tuple[int, list[str]], factory: str, hostname: str
) -> None:
    port, requests = completion_server
    _use_proxy(monkeypatch, "http://127.0.0.1:1")
    config = AIConfig(
        backend=AIBackend.OPENAI_COMPAT,
        base_url=f"http://{hostname}:{port}/v1",
        api_key="local-protocol-test",
        model="test-model",
        timeout=5,
    )
    with closing(get_openai_client(config) if factory == "analyzer" else build_llm_client(config)) as client:
        if factory == "analyzer":
            assert client.timeout.as_dict() == {"connect": 10, "read": 30, "write": 30, "pool": 10}
        else:
            assert client._client.timeout == 5
        request = {"model": "test-model", "messages": [{"role": "user", "content": "test"}], "temperature": 0.3}
        if factory == "analyzer":
            response = client.chat.completions.create(**request)
        else:
            response = client.chat_completions_create(**request)
        assert response.choices[0].message.content == "local reply"
    assert requests == ["/v1/chat/completions"]


@pytest.mark.parametrize("hostname", ["remote.invalid", "localhost.remote.invalid", "127.0.0.1.remote.invalid"])
def test_remote_completion_keeps_environment_proxy(
    monkeypatch: pytest.MonkeyPatch, completion_server: tuple[int, list[str]], hostname: str
) -> None:
    port, requests = completion_server
    _use_proxy(monkeypatch, f"http://127.0.0.1:{port}")
    with build_openai_client(api_key="proxy-protocol-test", base_url=f"http://{hostname}/v1", timeout=5) as client:
        response = client.chat.completions.create(model="test-model", messages=[{"role": "user", "content": "test"}])
        assert response.choices[0].message.content == "local reply"
    assert requests == [f"http://{hostname}/v1/chat/completions"]


def test_loopback_redirect_to_remote_still_uses_proxy(
    monkeypatch: pytest.MonkeyPatch, completion_server: tuple[int, list[str]]
) -> None:
    port, requests = completion_server
    _use_proxy(monkeypatch, f"http://127.0.0.1:{port}")
    with build_openai_client(
        api_key="local-protocol-test", base_url=f"http://127.0.0.1:{port}/redirect", timeout=5
    ) as client:
        response = client.chat.completions.create(model="test-model", messages=[{"role": "user", "content": "test"}])
        assert response.choices[0].message.content == "local reply"
    assert requests == ["/redirect/chat/completions", "http://remote.invalid/v1/chat/completions"]


def test_sdk_construction_failure_closes_owned_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    import openai

    actual_transport = openai.DefaultHttpxClient
    created = []

    def capture_transport(**kwargs):
        transport = actual_transport(**kwargs)
        created.append(transport)
        return transport

    def reject_client(**kwargs):
        raise ValueError("invalid SDK construction")

    monkeypatch.setattr(openai, "DefaultHttpxClient", capture_transport)
    monkeypatch.setattr(openai, "OpenAI", reject_client)
    with pytest.raises(ValueError, match="invalid SDK construction"):
        build_openai_client(api_key="local-protocol-test", base_url="http://localhost:1234/v1", timeout=5)
    assert len(created) == 1
    assert created[0].is_closed


@pytest.mark.parametrize("hostname", ["localhost", "127.0.0.1", "[::1]"])
def test_loopback_preserves_environment_ca_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, hostname: str
) -> None:
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "required-ca-not-present.pem"))
    # Ignoring TLS environment settings would construct a client successfully.
    with pytest.raises(FileNotFoundError):
        build_openai_client(api_key="local-protocol-test", base_url=f"https://{hostname}/v1", timeout=5)


@pytest.mark.parametrize("factory", [get_openai_client, build_llm_client])
def test_missing_openai_compatible_endpoint_is_rejected(factory) -> None:
    config = AIConfig(backend=AIBackend.OPENAI_COMPAT, api_key="test-key", model="test-model")
    with pytest.raises(ValueError, match="OPENAI_COMPAT backend requires"):
        factory(config)
