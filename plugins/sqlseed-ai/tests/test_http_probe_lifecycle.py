"""Failed local HTTP probes must close urllib's error responses."""

from __future__ import annotations

import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from .http_helpers import quiet_http_log

try:
    from sqlseed_ai.config import AIBackend, AIConfig
except ModuleNotFoundError as exc:
    if exc.name != "sqlseed_ai":
        raise
    pytest.skip("sqlseed-ai plugin not installed", allow_module_level=True)


class _UnavailableHandler(BaseHTTPRequestHandler):
    log_message = quiet_http_log

    def do_GET(self) -> None:
        """Return an actual error response whose file lifetime can be inspected."""
        self.send_response(503)
        self.send_header("Content-Length", "0")
        self.end_headers()


@pytest.mark.parametrize("probe", ["models", "speed", "mcp"])
def test_http_probe_closes_error_response(monkeypatch: pytest.MonkeyPatch, probe: str) -> None:
    if probe == "mcp":
        pytest.importorskip("mcp")
    errors: list[urllib.error.HTTPError] = []
    real_urlopen = urllib.request.urlopen
    config = AIConfig(backend=AIBackend.OLLAMA, model="test-model")
    with ThreadingHTTPServer(("127.0.0.1", 0), _UnavailableHandler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def open_local_error(*args: object, **kwargs: object) -> object:
            try:
                return real_urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=2)
            except urllib.error.HTTPError as error:
                errors.append(error)
                raise

        monkeypatch.setattr(urllib.request, "urlopen", open_local_error)
        try:
            if probe == "models":
                assert config.detect_all_local_models() == []
            elif probe == "speed":
                assert config.probe_inference_speed() is None
            else:
                from sqlseed_ai.mcp import _check_local_backend

                assert not _check_local_backend("ollama", "http://probe.invalid/")["available"]
            assert len(errors) == 1
            assert errors[0].closed
        finally:
            for error in errors:
                error.close()
            server.shutdown()
            thread.join(timeout=5)
