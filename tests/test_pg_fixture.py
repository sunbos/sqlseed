"""PostgreSQL test service selection and owned-container cleanup contracts."""

from __future__ import annotations

import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from tempfile import TemporaryDirectory
from threading import Event, Thread

import pytest

import conftest as shared


@pytest.fixture
def docker_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    docker_client = pytest.importorskip("testcontainers.core.docker_client")
    monkeypatch.setattr(docker_client.c, "tc_properties_get_tc_host", lambda: None)


def test_external_pg_service_does_not_require_or_start_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_TEST_URL", "postgresql+psycopg://localhost/isolated_test")
    monkeypatch.setattr(shared, "PostgresContainer", None)
    service = shared.pg_url.__wrapped__()
    try:
        assert next(service) == "postgresql+psycopg://localhost/isolated_test"
    except pytest.skip.Exception:
        pytest.fail("An explicitly configured PostgreSQL service must not require Docker")
    service.close()


def test_owned_container_is_stopped_when_startup_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PG_TEST_URL", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "tcp://fixture.example:2375")
    monkeypatch.setattr(shared, "_check_docker_endpoint", lambda: None)
    monkeypatch.setattr(shared, "_check_docker_daemon", lambda: None)
    stopped = []

    class FailedContainer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def start(self) -> None:
            raise ValueError("invalid database startup configuration")

        def stop(self) -> None:
            stopped.append(True)

    monkeypatch.setattr(shared, "PostgresContainer", FailedContainer)
    with pytest.raises(ValueError, match="invalid database startup configuration"):
        next(shared.pg_url.__wrapped__())
    assert stopped == [True]


@pytest.mark.parametrize("bound", [False, True], ids=["missing", "not-listening"])
@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="Python has no Unix socket support")
@pytest.mark.usefixtures("docker_environment")
def test_unavailable_unix_endpoint_is_closed_before_sdk_construction(
    monkeypatch: pytest.MonkeyPatch, bound: bool
) -> None:
    monkeypatch.delenv("PG_TEST_URL", raising=False)

    class UnexpectedContainer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pytest.fail("An unavailable Unix endpoint must not enter the Docker SDK")

    monkeypatch.setattr(shared, "PostgresContainer", UnexpectedContainer)
    # AF_UNIX paths have a small platform limit, so keep the temporary path short.
    with (
        TemporaryDirectory(prefix="sqpg-") as directory,
        monkeypatch.context() as context,
        socket.socket(socket.AF_UNIX) as endpoint,
    ):
        context.chdir(directory)
        path = "docker.sock"
        if bound:
            endpoint.bind(path)
        monkeypatch.setenv("DOCKER_HOST", f"unix://{path}")
        with pytest.raises(pytest.skip.Exception, match="Docker"):
            next(shared.pg_url.__wrapped__())


@pytest.mark.usefixtures("docker_environment")
@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="Python has no Unix socket support")
def test_unix_probe_closes_connection_and_owned_container_still_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PG_TEST_URL", raising=False)
    monkeypatch.setattr(shared, "_check_docker_daemon", lambda: None)
    lifecycle = []

    class AvailableContainer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            lifecycle.append("constructed")

        def start(self) -> None:
            lifecycle.append("started")

        def get_connection_url(self) -> str:
            return "postgresql+psycopg2://localhost/isolated_test"

        def stop(self) -> None:
            lifecycle.append("stopped")

    monkeypatch.setattr(shared, "PostgresContainer", AvailableContainer)
    with (
        TemporaryDirectory(prefix="sqpg-") as directory,
        monkeypatch.context() as context,
        socket.socket(socket.AF_UNIX) as endpoint,
    ):
        context.chdir(directory)
        path = "docker.sock"
        endpoint.bind(path)
        endpoint.listen(1)
        endpoint.settimeout(2)
        monkeypatch.setenv("DOCKER_HOST", f"unix://{path}")
        service = shared.pg_url.__wrapped__()
        try:
            assert next(service) == "postgresql+psycopg://localhost/isolated_test"
            with endpoint.accept()[0] as peer:
                peer.settimeout(2)
                assert peer.recv(1) == b""
        finally:
            service.close()
    assert lifecycle == ["constructed", "started", "stopped"]


@pytest.mark.usefixtures("docker_environment")
def test_docker_transport_error_is_unavailable_without_matching_message(monkeypatch: pytest.MonkeyPatch) -> None:
    from docker.errors import DockerException

    monkeypatch.delenv("PG_TEST_URL", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "npipe:////./pipe/docker_engine")
    monkeypatch.setattr(shared, "_check_docker_daemon", lambda: None)
    transport_error = FileNotFoundError(2, "The system cannot find the file specified.")
    if sys.platform == "win32":
        from pywintypes import error

        transport_error = error(2, "CreateFile", "The system cannot find the file specified.")

    class UnavailableContainer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise DockerException("Error while fetching server API version") from transport_error

    monkeypatch.setattr(shared, "PostgresContainer", UnavailableContainer)
    with pytest.raises(pytest.skip.Exception, match="Docker"):
        next(shared.pg_url.__wrapped__())


@pytest.mark.parametrize("message", ["Invalid response from docker daemon", "Docker startup configuration invalid"])
@pytest.mark.usefixtures("docker_environment")
def test_non_transport_failure_is_not_treated_as_unavailable(monkeypatch: pytest.MonkeyPatch, message: str) -> None:
    from docker.errors import DockerException

    failure = DockerException(message) if message.startswith("Invalid response") else ValueError(message)
    monkeypatch.delenv("PG_TEST_URL", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "tcp://fixture.example:2375")
    monkeypatch.setattr(shared, "_check_docker_daemon", lambda: None)

    class BrokenContainer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise failure

    monkeypatch.setattr(shared, "PostgresContainer", BrokenContainer)
    with pytest.raises(type(failure), match=str(failure)):
        next(shared.pg_url.__wrapped__())


@pytest.mark.parametrize("cause_kind", ["api", "tls", "http", "permission"])
@pytest.mark.usefixtures("docker_environment")
def test_wrapped_authentication_and_permission_errors_remain_failures(
    monkeypatch: pytest.MonkeyPatch, cause_kind: str
) -> None:
    from docker.errors import APIError, DockerException
    from requests.exceptions import HTTPError, SSLError

    causes = {
        "api": APIError("401 Unauthorized"),
        "tls": SSLError("certificate verification failed"),
        "http": HTTPError("403 Forbidden"),
        "permission": PermissionError(13, "Permission denied"),
    }
    if sys.platform == "win32":
        import pywintypes

        causes["permission"] = pywintypes.error(5, "CreateFile", "Access is denied.")
    monkeypatch.delenv("PG_TEST_URL", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "tcp://fixture.example:2375")
    monkeypatch.setattr(shared, "_check_docker_daemon", lambda: None)

    class BrokenContainer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise DockerException("Error while fetching server API version") from causes[cause_kind]

    monkeypatch.setattr(shared, "PostgresContainer", BrokenContainer)
    with pytest.raises(DockerException, match="Error while fetching server API version"):
        next(shared.pg_url.__wrapped__())


@pytest.fixture
def docker_info_endpoint(monkeypatch: pytest.MonkeyPatch, docker_environment: None):
    """Exercise the real SDK over HTTP and observe its connection closing."""
    import json

    response = {"status": 200, "body": {"OSType": "linux"}}
    disconnected = Event()
    requests = []

    class DockerInfoHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            requests.append(self.path)
            is_version = self.path == "/version"
            body = json.dumps({"ApiVersion": "1.55"} if is_version else response["body"]).encode()
            self.send_response(200 if is_version else response["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def finish(self) -> None:
            super().finish()
            disconnected.set()

        def log_message(self, message: str, *args: object) -> None:
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), DockerInfoHandler) as server:
        worker = Thread(target=server.serve_forever)
        worker.start()
        monkeypatch.setenv("DOCKER_HOST", f"tcp://127.0.0.1:{server.server_port}")
        monkeypatch.delenv("PG_TEST_URL", raising=False)
        try:
            yield response, disconnected, requests
        finally:
            server.shutdown()
            worker.join(timeout=5)


@pytest.mark.parametrize("daemon_os", ["linux", "windows", None], ids=["linux", "windows", "unknown"])
def test_daemon_capability_uses_server_os_and_closes_client(
    monkeypatch: pytest.MonkeyPatch, docker_info_endpoint, daemon_os: str | None
) -> None:
    response, disconnected, requests = docker_info_endpoint
    response["body"] = {"OSType": daemon_os} if daemon_os else {}
    lifecycle = []

    class AvailableContainer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            lifecycle.append("constructed")

        def start(self) -> None:
            lifecycle.append("started")

        def get_connection_url(self) -> str:
            return "postgresql+psycopg2://localhost/isolated_test"

        def stop(self) -> None:
            lifecycle.append("stopped")

    monkeypatch.setattr(shared, "PostgresContainer", AvailableContainer)
    service = shared.pg_url.__wrapped__()
    try:
        if daemon_os == "windows":
            with pytest.raises(pytest.skip.Exception, match="Linux Docker daemon"):
                next(service)
            assert lifecycle == []
        else:
            assert next(service) == "postgresql+psycopg://localhost/isolated_test"
    finally:
        service.close()
    assert disconnected.wait(2), "The Docker info client's HTTP connection must be closed"
    assert requests == ["/version", "/v1.55/info"]
    if daemon_os != "windows":
        assert lifecycle == ["constructed", "started", "stopped"]


@pytest.mark.parametrize("status", [401, 500])
def test_daemon_api_errors_are_not_hidden_and_client_is_closed(
    monkeypatch: pytest.MonkeyPatch, docker_info_endpoint, status: int
) -> None:
    from docker.errors import APIError

    response, disconnected, requests = docker_info_endpoint
    response.update(status=status, body={"message": "daemon rejected request"})

    class UnexpectedContainer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pytest.fail("A failed daemon capability query must not create PostgreSQL or Ryuk")

    monkeypatch.setattr(shared, "PostgresContainer", UnexpectedContainer)
    with pytest.raises(APIError, match="daemon rejected request"):
        next(shared.pg_url.__wrapped__())
    assert disconnected.wait(2), "The failed Docker info client's HTTP connection must be closed"
    assert requests == ["/version", "/v1.55/info"]
