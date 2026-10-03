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


@pytest.mark.parametrize(("lose_resume_ack", "delayed_shutdown"), [(False, False), (True, False), (True, True)])
def test_supervisor_preserves_port_connection_identity_and_database_after_package_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lose_resume_ack: bool,
    delayed_shutdown: bool,
) -> None:
    environment = importlib.import_module("sqlseed_web.plugin_environment")
    supervisor_module = importlib.import_module("sqlseed_web.supervisor")
    prefix = tmp_path / "environment"
    site = prefix / "site-packages"
    site.mkdir(parents=True)
    (prefix / "pyvenv.cfg").write_text("include-system-site-packages = false\n")

    def distribution(name: str) -> None:
        path = site / f"{name}-1.0.dist-info"
        path.mkdir()
        (path / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")

    for name in ("sqlseed", "sqlseed-web", "Faker"):
        distribution(name)
    monkeypatch.setattr(
        environment, "_environment", lambda: environment.Environment(prefix, sys.executable, "pip", None, None)
    )
    monkeypatch.setattr(environment, "_distribution_paths", lambda: [str(site)])
    monkeypatch.setenv("SQLSEED_WEB_WORKSPACE_PATH", str(tmp_path / "workspace.sqlite3"))
    supervisor = supervisor_module.Supervisor(port=0)
    installed_before = sorted((item.metadata["Name"], item.version) for item in metadata.distributions())
    invoked: list[str] = []
    old_process: Any = None
    uncertain_workers: list[Any] = []
    request = supervisor._request
    waiting_request: threading.Thread | None = None
    status_entered, release_status = threading.Event(), threading.Event()
    original_status = supervisor.manager.status
    arm_status = False

    def blocking_status() -> dict[str, Any]:
        if arm_status:
            status_entered.set()
            if not release_status.wait(30):
                raise RuntimeError("test status request was not released")
        return original_status()

    monkeypatch.setattr(supervisor.manager, "status", blocking_status)

    def read_status() -> None:
        with httpx.Client(timeout=30, trust_env=False) as client:
            client.get(f"http://127.0.0.1:{supervisor.port}/api/settings/plugins/management")

    def lose_one_ack(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        nonlocal waiting_request, arm_status
        result = request(method, params)
        if method == "resume" and invoked and lose_resume_ack and not uncertain_workers:
            # The real child has already resumed. Only its acknowledgement is
            # lost; recovery must drain that process, not forget or kill it.
            uncertain_workers.append(supervisor.process)
            if delayed_shutdown:
                arm_status = True
                waiting_request = threading.Thread(target=read_status)
                waiting_request.start()
                if not status_entered.wait(10):
                    raise RuntimeError("status request did not start")
                # Bound only this confirmed in-flight shutdown, leaving the
                # production startup budget and child lifecycle unchanged.
                monkeypatch.setattr(supervisor_module, "WORKER_STOP_TIMEOUT", 0.2)
            raise RuntimeError("private-password https://user:secret@example.test")
        return result

    monkeypatch.setattr(supervisor, "_request", lose_one_ack)

    def controlled_installer(arguments: list[str], output: Any, **kwargs: Any) -> int:
        assert supervisor.mode == "maintenance"
        assert not old_process.is_alive()
        invoked.append(arguments[-1])
        distribution("mimesis")
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
        base = f"http://127.0.0.1:{supervisor.port}"
        with httpx.Client(base_url=base, timeout=10, trust_env=False) as client:
            status = client.get("/api/settings/plugins/management").json()
            assert status["automatic_lifecycle"] is True
            headers = {"Origin": base, "X-Sqlseed-Management-Token": status["token"]}
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
            response = client.post(
                "/api/settings/plugins/execute", headers=headers, json={"plan_id": plan.json()["plan_id"]}
            )
            assert response.status_code == 202, response.text
            task_id = response.json()["task_id"]
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
                assert len(uncertain_workers) == 1
                if delayed_shutdown:
                    assert supervisor.process is uncertain_workers[0]
                    assert supervisor.process.is_alive()
                    release_status.set()
                    waiting_request.join(timeout=10)
                    assert not waiting_request.is_alive()
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
            status = client.get("/api/settings/plugins/management").json()
            assert status["service_generation"] == 2
            assert status["session_restore"]["restored_connections"] == 1
            assert status["instance_id"]
            restored = client.get("/api/connections").json()
            assert any(item["conn_id"] == conn_id for item in restored["connections"])
            assert client.get(f"/api/connections/{conn_id}/tables").status_code == 200
            assert supervisor.process.pid != old_process.pid
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
            assert run["status"] == "done" and run["rows_inserted"] == 2, run
        assert invoked == ["mimesis"]
        with sqlite_connection(database) as connection:
            rows = connection.execute("SELECT * FROM users ORDER BY id").fetchall()
            assert len(rows) == 3 and rows[0] == (1, "kept")
        assert installed_before == sorted((item.metadata["Name"], item.version) for item in metadata.distributions())
        # An orphan keeps the environment locked until its existing work has
        # drained. Losing the private parent channel then ends the worker.
        supervisor.manager._environment_lock.release()
        contender = environment.EnvironmentLock(prefix, exclusive=True)
        with pytest.raises(RuntimeError):
            contender.acquire()
        supervisor.channel.close()
        supervisor.process.join(timeout=5)
        assert not supervisor.process.is_alive()
        contender.acquire()
        contender.release()
    finally:
        release_status.set()
        if waiting_request is not None:
            waiting_request.join(timeout=10)
        supervisor.stop()


def _exit_before_ready(*args: Any) -> None:
    os._exit(19)


def _never_ready(*args: Any) -> None:
    threading.Event().wait(60)


@pytest.mark.parametrize(
    ("target", "code", "exit_code"),
    [(_exit_before_ready, "worker_exited_before_ready", 19), (_never_ready, "worker_startup_timeout", None)],
)
def test_real_worker_exit_and_timeout_have_distinct_safe_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: Any, code: str, exit_code: int | None
) -> None:
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
        assert failed.value.detail["phase"] == "boot"
        assert failed.value.detail["exit_code"] == exit_code
        assert supervisor.process is None
        assert supervisor.channel is None
    finally:
        supervisor.stop()
