"""Real HTTP/process swaps with an isolated, controlled installer boundary."""

from __future__ import annotations

import importlib
import sqlite3
import sys
import time
from contextlib import closing
from importlib import metadata
from pathlib import Path
from typing import Any

import httpx
import pytest


@pytest.mark.skipif(sys.platform == "win32", reason="Managed worker replacement requires POSIX descriptor inheritance")
def test_supervisor_preserves_port_connection_identity_and_database_after_package_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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

    def controlled_installer(arguments: list[str], output: Any, **kwargs: Any) -> int:
        assert supervisor.mode == "maintenance"
        assert not old_process.is_alive()
        invoked.append(arguments[-1])
        distribution("mimesis")
        return 0

    monkeypatch.setattr("sqlseed_web.plugin_management.run_installer", controlled_installer)
    database = tmp_path / "data.sqlite3"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT); INSERT INTO users VALUES (1, 'kept');"
        )
    supervisor.start()
    try:
        old_process = supervisor.process
        base = f"http://127.0.0.1:{supervisor.port}"
        with httpx.Client(base_url=base, timeout=5) as client:
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
            deadline = time.monotonic() + 20
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
            assert result.get("status") == "succeeded", result
            assert result["service_ready"] is True
            status = client.get("/api/settings/plugins/management").json()
            assert status["service_generation"] == 2
            assert status["session_restore"]["restored_connections"] == 1
            assert status["instance_id"]
            restored = client.get("/api/connections").json()
            assert any(item["conn_id"] == conn_id for item in restored["connections"])
            assert client.get(f"/api/connections/{conn_id}/tables").status_code == 200
            assert supervisor.process.pid != old_process.pid
        assert invoked == ["mimesis"]
        with closing(sqlite3.connect(database)) as connection, connection:
            assert connection.execute("SELECT * FROM users").fetchall() == [(1, "kept")]
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
        supervisor.stop()
