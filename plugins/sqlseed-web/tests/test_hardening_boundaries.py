"""Exercise the exact defensive branches missing from PR 23's coverage report."""

from __future__ import annotations

import copy
import pickle
import subprocess
import sys
import threading
from contextlib import ExitStack, closing
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
from packaging.tags import sys_tags

from sqlseed_web import plugin_environment, plugin_updates, workbench_ai
from sqlseed_web.plugin_management import ExecuteRequest, PlanRequest
from sqlseed_web.plugin_process import run_installer

from .test_plugin_process import fixture_recorded_processes
from .test_plugin_updates import fixture_update_manager
from .test_workbench_ai import fixture_ai_client

# Re-export the existing fixture registrations without importing their test functions.
__all__ = ["fixture_ai_client", "fixture_recorded_processes", "fixture_update_manager"]


def test_wheel_selection_rejects_invalid_entries_and_preserves_priority_and_ties() -> None:
    preferred_tag = next(sys_tags())
    winner = {"filename": f"mimesis-2.0-1-{preferred_tag}.whl", "core-metadata": True}
    payload = {
        "files": [
            None,
            {"filename": "mimesis-2.0-py3-none-any.whl", "core-metadata": True, "yanked": True},
            {"filename": ["not a name"]},
            {"filename": "../mimesis-2.0-py3-none-any.whl"},
            {"filename": "invalid.whl", "core-metadata": True},
            {"filename": "unrelated-2.0-py3-none-any.whl", "core-metadata": True},
            {"filename": "mimesis-1.0-py3-none-any.whl", "core-metadata": True},
            {"filename": "mimesis-2.0-cp27-cp27m-win32.whl", "core-metadata": True},
            {"filename": "mimesis-2.0-py3-none-any.whl", "core-metadata": True},
            {"filename": f"mimesis-2.0-2-{preferred_tag}.whl", "core-metadata": True},
            winner,
        ]
    }
    original = copy.deepcopy(payload)
    assert plugin_updates._select_wheel(payload, "mimesis", "2.0") is winner
    assert payload == original


@pytest.mark.parametrize("payload", [None, [], "private invalid index"])
def test_wheel_selection_rejects_a_non_object_index_without_echoing_it(payload: object) -> None:
    with pytest.raises(TypeError) as raised:
        plugin_updates._select_wheel(payload, "mimesis", "2.0")
    assert "private invalid index" not in str(raised.value)


def test_failed_network_worker_start_releases_admission_for_a_real_request(monkeypatch: pytest.MonkeyPatch) -> None:
    # An isolated real semaphore keeps a failing ownership regression from
    # contaminating later tests while retaining the production one-slot policy.
    monkeypatch.setattr(plugin_updates, "_NETWORK_SLOT", threading.BoundedSemaphore(1))
    requests: list[str] = []
    body = b'{"version":"2.0"}'
    failure = RuntimeError("cannot start update worker")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def failed_start(*args: object, **kwargs: object) -> None:
        raise failure

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        server.timeout = 3

        def read_metadata() -> bytes:
            # The retry must still own the sole slot for its whole request.
            with pytest.raises(ValueError):
                plugin_updates._bounded_network(lambda: pytest.fail("concurrent operation was admitted"), timeout=0)
            with closing(HTTPConnection("127.0.0.1", server.server_port, timeout=2)) as connection:
                connection.request("GET", "/metadata")
                response = connection.getresponse()
                assert response.status == 200
                return response.read()

        with monkeypatch.context() as fault:
            fault.setattr(plugin_updates, "DaemonTask", failed_start)
            with pytest.raises(RuntimeError) as raised:
                plugin_updates._bounded_network(read_metadata, timeout=5)
        assert raised.value is failure
        assert not requests

        worker = threading.Thread(target=server.handle_request, name="test-update-metadata", daemon=True)
        worker.start()
        try:
            assert plugin_updates._bounded_network(read_metadata, timeout=5) == body
        finally:
            worker.join(timeout=5)
        assert not worker.is_alive()
    assert requests == ["/metadata"]
    assert plugin_updates._bounded_network(lambda: "admission released again", timeout=2) == "admission released again"


def test_missing_verified_update_fails_before_installer_and_restores_service(update_manager: Any) -> None:
    manager, _, events, installs = update_manager
    before = plugin_environment.installed_packages(manager.environment.prefix)
    plan = manager.plan(PlanRequest(component_id="mimesis", action="update"))
    assert manager._plan is not None
    # Corrupt only the internal prepared artifact, after the public review succeeds.
    manager._plan.pop("_update")
    task = manager.execute(ExecuteRequest(plan_id=plan["plan_id"]))
    assert manager._worker is not None
    manager._worker.join(5)
    assert not manager._worker.is_alive()
    completed = manager.task_snapshot(task["task_id"])
    assert completed["status"] == "failed"
    assert completed["service_ready"] is True
    assert completed["returncode"] is None
    assert not installs
    assert events == ["pause", "maintenance", "restore"]
    assert plugin_environment.installed_packages(manager.environment.prefix) == before


def test_output_callback_failure_is_classified_and_the_real_installer_is_reaped(
    recorded_processes: list[subprocess.Popen[bytes]],
) -> None:
    callback_error = OSError("private-output-sink-detail")
    received: list[str] = []

    def broken_output(text: str) -> None:
        received.append(text)
        raise callback_error

    with pytest.raises(RuntimeError) as raised:
        run_installer([sys.executable, "-c", "print('installer report')"], broken_output, timeout=10)
    assert received == ["installer report"]
    assert raised.value.__cause__ is callback_error
    assert "private-output-sink-detail" not in str(raised.value)
    assert recorded_processes
    for process in recorded_processes:
        assert process.poll() is not None
        if process.stdout is not None:
            assert process.stdout.closed


def test_model_connection_failure_is_safe_and_releases_the_request_for_retry(
    ai_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, registry, payload = ai_client
    connection = registry.get_connection(payload["conn_id"])
    original_users = connection.orchestrator.query("SELECT * FROM users")
    attempted: list[object] = []

    def model(messages: Any, **kwargs: Any) -> dict[str, Any]:
        attempted.append(messages)
        if len(attempted) == 1:
            try:
                raise ConnectionError("private-model-endpoint-detail")
            except ConnectionError as cause:
                raise RuntimeError("private-outer-request-detail") from cause
        return {"suggestions": []}

    monkeypatch.setattr(workbench_ai, "_call_model", model)
    failed = client.post("/api/workbench/ai/suggest", json=payload)
    assert failed.status_code == 502
    assert failed.json()["detail"]["code"] == "ai_connection_failed"
    assert "private-model" not in failed.text and "private-outer" not in failed.text
    assert client.post("/api/workbench/ai/suggest", json=payload).status_code == 200
    assert len(attempted) == 2
    assert connection.orchestrator.query("SELECT * FROM users") == original_users
    assert connection.orchestrator.get_row_count("orders") == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 environment handles require an active spawn")
def test_serializing_an_environment_lock_outside_spawn_preserves_its_ownership(tmp_path: Path) -> None:
    owner = plugin_environment.EnvironmentLock(tmp_path, exclusive=True)
    contender = plugin_environment.EnvironmentLock(tmp_path, exclusive=True)
    with ExitStack() as cleanup:
        cleanup.callback(owner.release)
        cleanup.callback(contender.release)
        owner.acquire()
        with pytest.raises(RuntimeError, match="while spawning a worker"):
            pickle.dumps(plugin_environment.InheritedEnvironmentLock(owner.fileno()))
        with pytest.raises(RuntimeError):
            contender.acquire()
        owner.release()
        contender.acquire()
