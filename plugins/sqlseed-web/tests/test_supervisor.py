"""Real HTTP/process swaps with an isolated, controlled installer boundary."""

from __future__ import annotations

import importlib
import os
import sys
import threading
import time
from importlib import metadata
from pathlib import Path
from typing import Any

import httpx
import pytest
from tests.sqlite_helpers import sqlite_connection


def _wait_for_task_result(client: httpx.Client, task_id: str) -> dict[str, Any]:
    """Poll across temporary HTTP outages with a fixed task completion deadline."""
    deadline = time.monotonic() + 90
    result: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            response = client.get(f"/api/settings/plugins/tasks/{task_id}")
            if response.status_code == 200:
                result = response.json()
                if result["status"] != "running":
                    break
        except httpx.TransportError:
            pass
        time.sleep(0.05)
    return result


def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Path, Path]:
    """Use temporary distribution metadata and workspace files without changing installed packages."""
    environment = importlib.import_module("sqlseed_web.plugin_environment")
    prefix = tmp_path / "environment"
    site = prefix / "site-packages"
    site.mkdir(parents=True)
    (prefix / "pyvenv.cfg").write_text("include-system-site-packages = false\n")
    for name in ("sqlseed", "sqlseed-web", "Faker"):
        _create_distribution(site, name)
    monkeypatch.setattr(
        environment, "_environment", lambda: environment.Environment(prefix, sys.executable, "pip", None, None)
    )
    monkeypatch.setattr(environment, "_distribution_paths", lambda: [str(site)])
    monkeypatch.setenv("SQLSEED_WEB_WORKSPACE_PATH", str(tmp_path / "workspace.sqlite3"))
    return environment, prefix, site


def _create_distribution(site: Path, name: str) -> None:
    """Represent one installed component inside the isolated test environment."""
    path = site / f"{name}-1.0.dist-info"
    path.mkdir()
    (path / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")


def _connect_and_start_package_task(
    client: httpx.Client, supervisor: Any, database: Path
) -> tuple[dict[str, str], str, str]:
    """Create a real database connection and submit a confirmed component operation over HTTP."""
    status = client.get("/api/settings/plugins/management").json()
    assert status["automatic_lifecycle"] is True
    headers = {"Origin": str(client.base_url).rstrip("/"), "X-Sqlseed-Management-Token": status["token"]}
    response = client.post("/api/connections", json={"db_path": str(database), "provider": "faker"})
    assert response.status_code == 200, response.text
    conn_id = response.json()["conn_id"]
    plan = client.post(
        "/api/settings/plugins/plan", headers=headers, json={"component_id": "mimesis", "action": "install"}
    )
    assert plan.status_code == 200, plan.text
    for _ in range(100):
        if not any(supervisor._request("activity").values()):
            break
        time.sleep(0.01)
    response = client.post("/api/settings/plugins/execute", headers=headers, json={"plan_id": plan.json()["plan_id"]})
    assert response.status_code == 202, response.text
    return headers, conn_id, response.json()["task_id"]


def _assert_failed_recovery(result: dict[str, Any], *, delayed_shutdown: bool) -> None:
    """Require actionable lifecycle facts without disclosing the injected private exception."""
    assert result["status"] == "failed", result
    assert result["stage"] == "recovery_failed"
    assert result["service_ready"] is False
    code = "worker_shutdown_timeout" if delayed_shutdown else "worker_resume_failed"
    assert result["recovery_error"]["code"] == code
    assert result["recovery_error"]["phase"] == ("shutdown" if delayed_shutdown else "resume")
    assert result["recovery_error"]["elapsed_ms"] >= 0
    assert result["recovery_error"]["message_key"] == f"backend.supervisor.{code}"
    assert result["output_i18n"][-1]["key"] == f"backend.supervisor.{code}"
    assert "private-password" not in str(result)
    assert "user:secret" not in str(result)


def _assert_restored_connection_and_generate(client: httpx.Client, conn_id: str) -> None:
    """Verify the recovered connection still supports schema checks and actual row generation."""
    status = client.get("/api/settings/plugins/management").json()
    assert status["service_generation"] == 2
    assert status["session_restore"]["restored_connections"] == 1
    assert status["instance_id"]
    restored = client.get("/api/connections").json()
    assert any(item["conn_id"] == conn_id for item in restored["connections"])
    assert client.get(f"/api/connections/{conn_id}/tables").status_code == 200
    schema = client.get(f"/api/workbench/connections/{conn_id}/schema").json()
    document = {"provider": "base", "tables": [{"name": "users", "count": 2}]}
    inputs = {"conn_id": conn_id, "schema_hash": schema["schema_hash"], "document": document}
    draft = client.post("/api/workbench/drafts", json={**inputs, "name": "After recovery"}).json()
    checked = client.post("/api/workbench/check", json=inputs).json()
    assert checked["ok"], checked
    run = client.post(
        "/api/workbench/runs",
        json={
            "conn_id": conn_id,
            "draft_id": draft["id"],
            "revision": draft["revision"],
            "schema_hash": draft["schema_hash"],
            "config_hash": checked["config_hash"],
        },
    ).json()
    deadline = time.monotonic() + 20
    while run["status"] in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.02)
        run = client.get(f"/api/workbench/runs/{run['id']}").json()
    assert run["status"] == "done", run
    assert run["rows_inserted"] == 2, run


def _assert_orphan_retains_environment_lock(supervisor: Any, environment: Any, prefix: Path) -> None:
    # Losing the private parent channel must drain work before releasing the lock.
    """Keep a contender excluded until the real orphan has drained and exited."""
    supervisor.manager._environment_lock.release()
    contender = environment.EnvironmentLock(prefix, exclusive=True)
    with pytest.raises(RuntimeError):
        contender.acquire()
    supervisor.channel.close()
    supervisor.process.join(timeout=5)
    assert not supervisor.process.is_alive()
    contender.acquire()
    contender.release()


def _assert_running_worker_cannot_be_overwritten(supervisor: Any) -> None:
    """Reject replacement while the current process and control channel are still owned."""
    from sqlseed_web.managed_worker import WorkerLifecycleError

    original_process, original_channel = supervisor.process, supervisor.channel
    with pytest.raises(WorkerLifecycleError) as failed:
        supervisor._spawn("maintenance")
    assert failed.value.detail["code"] == "worker_stop_pending"
    assert failed.value.detail["phase"] == "shutdown"
    assert supervisor.process is original_process
    assert supervisor.channel is original_channel
    assert original_process.is_alive()
    assert supervisor.mode == "business"


def _inject_resume_ack_loss(
    supervisor: Any, monkeypatch: pytest.MonkeyPatch, invoked: list[str], *, enabled: bool, delayed_shutdown: bool
) -> tuple[threading.Event, list[threading.Thread], list[Any]]:
    """Lose one real resume acknowledgement, optionally holding an admitted request."""
    supervisor_module = importlib.import_module("sqlseed_web.supervisor")
    request = supervisor._request
    original_status = supervisor.manager.status
    uncertain_workers: list[Any] = []
    waiting_requests: list[threading.Thread] = []
    status_entered, release_status = threading.Event(), threading.Event()
    arm_status = False

    def blocking_status() -> dict[str, Any]:
        """Hold an admitted HTTP request until the test permits the worker to drain."""
        if arm_status:
            status_entered.set()
            if not release_status.wait(30):
                raise RuntimeError("test status request was not released")
        return original_status()

    def read_status() -> None:
        """Issue the real HTTP request used to keep shutdown busy."""
        with httpx.Client(timeout=30, trust_env=False) as client:
            client.get(f"http://127.0.0.1:{supervisor.port}/api/settings/plugins/management")

    def lose_one_ack(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Drop one reply after the real worker has already resumed admission."""
        nonlocal arm_status
        result = request(method, params)
        if method == "resume" and invoked and enabled and not uncertain_workers:
            # The real child has resumed. Only its acknowledgement is lost;
            # recovery must drain that process, not forget or kill it.
            uncertain_workers.append(supervisor.process)
            if delayed_shutdown:
                arm_status = True
                waiting = threading.Thread(target=read_status)
                waiting_requests.append(waiting)
                waiting.start()
                if not status_entered.wait(10):
                    raise RuntimeError("status request did not start")
                # Bound this confirmed in-flight shutdown, not normal startup.
                monkeypatch.setattr(supervisor_module, "WORKER_STOP_TIMEOUT", 0.2)
            raise RuntimeError("private-password https://user:secret@example.test")
        return result

    monkeypatch.setattr(supervisor.manager, "status", blocking_status)
    monkeypatch.setattr(supervisor, "_request", lose_one_ack)
    return release_status, waiting_requests, uncertain_workers


@pytest.mark.parametrize(("lose_resume_ack", "delayed_shutdown"), [(False, False), (True, False), (True, True)])
def test_supervisor_preserves_port_connection_identity_and_database_after_package_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lose_resume_ack: bool,
    delayed_shutdown: bool,
) -> None:
    """Retain rows and connection identity through normal, uncertain and delayed worker recovery."""
    environment, prefix, site = _isolated_environment(tmp_path, monkeypatch)
    supervisor_module = importlib.import_module("sqlseed_web.supervisor")
    supervisor = supervisor_module.Supervisor(port=0)
    installed_before = sorted((item.metadata["Name"], item.version) for item in metadata.distributions())
    invoked: list[str] = []
    old_process: Any = None
    release_status, waiting_requests, uncertain_workers = _inject_resume_ack_loss(
        supervisor, monkeypatch, invoked, enabled=lose_resume_ack, delayed_shutdown=delayed_shutdown
    )

    def controlled_installer(arguments: list[str], output: Any, **kwargs: Any) -> int:
        """Change only temporary metadata after the old business worker has exited."""
        assert supervisor.mode == "maintenance"
        assert not old_process.is_alive()
        invoked.append(arguments[-1])
        _create_distribution(site, "mimesis")
        return 0

    monkeypatch.setattr("sqlseed_web.plugin_management.run_installer", controlled_installer)
    database = tmp_path / "data.sqlite3"
    with sqlite_connection(database) as connection:
        connection.executescript(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT); INSERT INTO users VALUES (1, 'kept');"
        )
    supervisor.start()
    try:
        old_process = supervisor.process
        _assert_running_worker_cannot_be_overwritten(supervisor)
        base = f"http://127.0.0.1:{supervisor.port}"
        with httpx.Client(base_url=base, timeout=10, trust_env=False) as client:
            headers, conn_id, task_id = _connect_and_start_package_task(client, supervisor, database)
            if delayed_shutdown:
                from sqlseed_web.messages import materialize_messages

                # The draining listener intentionally cannot serve a fresh
                # request yet. Inspect the owner's terminal state, then verify
                # HTTP recovery once ensure_worker replaces that dead worker.
                supervisor.manager._worker.join(timeout=90)
                assert not supervisor.manager._worker.is_alive()
                result = materialize_messages(supervisor.manager.task_snapshot(task_id))
            else:
                result = _wait_for_task_result(client, task_id)
            if lose_resume_ack:
                _assert_failed_recovery(result, delayed_shutdown=delayed_shutdown)
                assert len(uncertain_workers) == 1
                if delayed_shutdown:
                    assert supervisor.process is uncertain_workers[0]
                    assert supervisor.process.is_alive()
                    release_status.set()
                    waiting_requests[0].join(timeout=10)
                    assert not waiting_requests[0].is_alive()
                    uncertain_workers[0].join(timeout=10)
                    supervisor.manager._worker.join(timeout=5)
                    monkeypatch.setattr(supervisor_module, "WORKER_STOP_TIMEOUT", 20)
                    supervisor.ensure_worker()
                assert uncertain_workers[0].exitcode == 0, "Resumed worker must drain and exit naturally"
                assert not uncertain_workers[0].is_alive()
                assert supervisor.mode == "maintenance"
                assert supervisor.process.pid != uncertain_workers[0].pid
                assert client.get("/api/connections").status_code == 503
                management = client.get("/api/settings/plugins/management").json()
                assert management["recovery_error"] == result["recovery_error"]
                assert client.post("/api/settings/plugins/recover", headers=headers, json={}).status_code == 202
                result = _wait_for_task_result(client, task_id)
            assert result.get("status") == "succeeded", result
            assert result["service_ready"] is True
            assert result["recovery_error"] is None
            assert supervisor.process.pid != old_process.pid
            _assert_restored_connection_and_generate(client, conn_id)
        assert invoked == ["mimesis"]
        with sqlite_connection(database) as connection:
            rows = connection.execute("SELECT * FROM users ORDER BY id").fetchall()
            assert len(rows) == 3
            assert rows[0] == (1, "kept")
        assert installed_before == sorted((item.metadata["Name"], item.version) for item in metadata.distributions())
        _assert_orphan_retains_environment_lock(supervisor, environment, prefix)
    finally:
        release_status.set()
        for waiting in waiting_requests:
            waiting.join(timeout=10)
        supervisor.stop()


def _exit_before_ready(*args: Any) -> None:
    """Produce a real child exit code before any readiness message is sent."""
    os._exit(19)


def _never_ready(*args: Any) -> None:
    """Keep an idle test child alive until the supervisor enforces its startup deadline."""
    threading.Event().wait(60)


def _report_failure_before_ready(listener: Any, connection: Any, mode: str, *args: Any) -> None:
    """Send application-stage failure through real IPC before the child is stopped."""
    from sqlseed_web.worker_control import ControlChannel

    channel = ControlChannel(connection)
    channel.start(lambda method, params: {})
    try:
        channel.call("worker_starting", {"mode": mode, "phase": "application"})
        channel.call("worker_failed", {"mode": mode, "phase": "application"})
        threading.Event().wait(60)
    finally:
        channel.close()
        listener.close()


@pytest.mark.parametrize(
    ("target", "code", "exit_code", "phase"),
    [
        (_exit_before_ready, "worker_exited_before_ready", 19, "boot"),
        (_never_ready, "worker_startup_timeout", None, "boot"),
        (_report_failure_before_ready, "worker_startup_failed", None, "application"),
    ],
)
def test_real_worker_exit_and_timeout_have_distinct_safe_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: Any, code: str, exit_code: int | None, phase: str
) -> None:
    """Distinguish process exit, startup timeout and explicit initialization failure."""
    from dataclasses import replace

    from sqlseed_web import supervisor as module
    from sqlseed_web.managed_worker import WorkerLifecycleError

    supervisor = module.Supervisor(port=0)
    supervisor.manager.environment = replace(supervisor.manager.environment, reason="test startup only")
    monkeypatch.setattr(module, "run_worker", target)
    if target is _never_ready:
        monkeypatch.setattr(module, "WORKER_START_TIMEOUT", 0.2)
    try:
        with pytest.raises(WorkerLifecycleError) as failed:
            supervisor.start()
        assert failed.value.detail["code"] == code
        assert failed.value.detail["phase"] == phase
        assert failed.value.detail["exit_code"] == exit_code
        assert supervisor.process is None
        assert supervisor.channel is None
    finally:
        supervisor.stop()


@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("worker_starting", {"mode": "maintenance", "phase": "application"}),
        ("worker_failed", {"mode": "business", "phase": "private-phase"}),
        ("worker_ready", {"mode": "maintenance", "restoration": {"connections": "untrusted"}}),
    ],
)
def test_supervisor_rejects_startup_reports_from_wrong_worker_without_changing_state(
    method: str, params: dict[str, Any]
) -> None:
    """Reject mismatched worker reports without advancing startup or restoring untrusted state."""
    from sqlseed_web.supervisor import Supervisor

    supervisor = Supervisor(port=0)
    supervisor.mode = "business"
    with pytest.raises(ValueError):
        supervisor._handle(method, params)
    assert supervisor._startup_phase == "boot"
    assert supervisor._startup_failed is False
    assert not supervisor._ready.is_set()
    assert not supervisor._restoration


def test_supervisor_process_start_failure_closes_transport_and_preserves_safe_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Release the real transport and listener when the operating-system spawn boundary fails."""
    from dataclasses import replace
    from multiprocessing.context import SpawnProcess

    from sqlseed_web import supervisor as module
    from sqlseed_web.managed_worker import WorkerLifecycleError

    channels = []
    original_channel = module.ControlChannel

    class TrackedChannel(original_channel):
        def __init__(self, connection: Any) -> None:
            """Record the real channel so cleanup can be inspected after failed process creation."""
            super().__init__(connection)
            channels.append(self)

    def unavailable_process(self: Any) -> None:
        """Fail before process creation with a private diagnostic that must not become public."""
        raise OSError("private-password https://user:secret@example.test")

    monkeypatch.setattr(module, "ControlChannel", TrackedChannel)
    monkeypatch.setattr(SpawnProcess, "start", unavailable_process)
    supervisor = module.Supervisor(port=0)
    supervisor.manager.environment = replace(supervisor.manager.environment, reason="test startup only")
    try:
        with pytest.raises(WorkerLifecycleError) as failed:
            supervisor.start()
        assert failed.value.detail["code"] == "worker_startup_failed"
        assert failed.value.detail["phase"] == "boot"
        assert failed.value.detail["exit_code"] is None
        assert failed.value.detail["elapsed_ms"] >= 0
        assert "private-password" not in str(failed.value.detail)
        assert "user:secret" not in str(failed.value.detail)
        assert len(channels) == 1
        assert channels[0].wait_closed(0)
        assert channels[0].connection.closed
        assert supervisor.process is None
        assert supervisor.channel is None
        assert supervisor.mode is None
        assert supervisor.listener is None
    finally:
        supervisor.stop()
