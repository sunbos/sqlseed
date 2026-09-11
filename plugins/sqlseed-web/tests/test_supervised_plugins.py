"""Supervised package tasks recover the business process before publishing completion."""

from __future__ import annotations

import importlib
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

import pytest
from fastapi import HTTPException


@pytest.fixture
def managed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    environment = importlib.import_module("sqlseed_web.plugin_environment")
    module = importlib.import_module("sqlseed_web.supervised_plugins")
    root = tmp_path / "venv"
    site = root / "site"
    site.mkdir(parents=True)
    (root / "pyvenv.cfg").write_text("include-system-site-packages = false\n")

    def install(name: str) -> None:
        path = site / f"{name}-1.0.dist-info"
        path.mkdir()
        (path / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")

    for name in ("sqlseed", "sqlseed-web", "Faker"):
        install(name)
    monkeypatch.setattr(
        environment, "_environment", lambda: environment.Environment(root, sys.executable, "pip", None, None)
    )
    monkeypatch.setattr(environment, "_distribution_paths", lambda: [str(site)])

    class Controller:
        calls: ClassVar[list[str]] = []
        busy = False
        restoration_error = False

        def pause(self) -> None:
            if self.busy:
                raise HTTPException(409, detail={"code": "plugin_management_busy", "message": "正在生成数据。"})
            self.calls.append("pause")

        def resume(self) -> None:
            self.calls.append("resume")

        def enter_maintenance(self) -> None:
            self.calls.append("maintenance")

        def restore_business(self) -> dict[str, Any]:
            self.calls.append("restore")
            if self.restoration_error:
                raise RuntimeError("private-error")
            return {"restored_connections": 1, "failed_connections": [], "ai_session_restored": True}

    controller = Controller()
    manager = module.SupervisedPluginManager(controller)
    manager.start()
    calls: list[Any] = []

    def runner(arguments: list[str], output: Any, **kwargs: Any) -> int:
        calls.append(arguments)
        assert controller.calls == ["pause", "maintenance"]
        install("mimesis")
        return 0

    monkeypatch.setattr("sqlseed_web.plugin_management.run_installer", runner)
    yield manager, controller, calls
    manager.stop()


def test_supervised_task_restores_business_before_reporting_success(managed: Any) -> None:
    module = importlib.import_module("sqlseed_web.plugin_management")
    manager, controller, calls = managed
    plan = manager.plan(module.PlanRequest(component_id="mimesis", action="install"))
    assert "自动" in " ".join(plan["warnings"])
    task = manager.execute(module.ExecuteRequest(plan_id=plan["plan_id"]))
    manager._worker.join(5)
    task = manager.task_snapshot(task["task_id"])
    assert task["status"] == "succeeded" and task["service_ready"] is True
    assert controller.calls == ["pause", "maintenance", "restore"]
    assert calls
    status = manager.status()
    assert status["automatic_lifecycle"] is True
    assert status["phase"] == "ready" and status["service_generation"] == 2
    assert status["restart_required"] is False
    assert status["session_restore"]["restored_connections"] == 1


def test_busy_worker_blocks_before_any_package_task(managed: Any) -> None:
    module = importlib.import_module("sqlseed_web.plugin_management")
    manager, controller, calls = managed
    plan = manager.plan(module.PlanRequest(component_id="mimesis", action="install"))
    controller.busy = True
    with pytest.raises(HTTPException) as error:
        manager.execute(module.ExecuteRequest(plan_id=plan["plan_id"]))
    assert error.value.status_code == 409
    assert manager.status()["active_task"] is None
    assert calls == []


def test_restoration_failure_is_recoverable_without_repeating_install(managed: Any) -> None:
    module = importlib.import_module("sqlseed_web.plugin_management")
    manager, controller, calls = managed
    controller.restoration_error = True
    plan = manager.plan(module.PlanRequest(component_id="mimesis", action="install"))
    manager.execute(module.ExecuteRequest(plan_id=plan["plan_id"]))
    manager._worker.join(5)
    assert manager.status()["phase"] == "recovery_failed"
    assert manager.status()["active_task"]["status"] == "failed"
    assert "private-error" not in str(manager.status())
    controller.restoration_error = False
    manager.recover()
    manager._worker.join(5)
    assert manager.status()["phase"] == "ready"
    assert manager.status()["active_task"]["service_ready"] is True
    assert len(calls) == 1


def test_supervisor_detects_a_dead_worker_and_keeps_a_recovery_page(
    managed: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module("sqlseed_web.supervisor")
    manager = managed[0]
    supervisor = module.Supervisor(port=0)
    supervisor.manager = manager

    class DeadProcess:
        def is_alive(self) -> bool:
            return False

    supervisor.process = DeadProcess()
    supervisor.mode = "business"
    modes: list[str] = []
    monkeypatch.setattr(supervisor, "_spawn", lambda mode: modes.append(mode))
    supervisor.ensure_worker()
    assert modes == ["maintenance"]
    assert manager.status()["phase"] == "recovery_failed"
    assert manager.status()["service_ready"] is False
    assert manager.status()["session_restore"]["session_lost"] is True


def test_a_worker_already_shutting_down_is_not_reported_as_resumed(
    managed: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module("sqlseed_web.supervisor")
    supervisor = module.Supervisor(port=0)
    supervisor.manager = managed[0]

    class LiveProcess:
        def is_alive(self) -> bool:
            return True

    supervisor.process = LiveProcess()
    supervisor.mode = "business"
    supervisor._shutdown_requested = True
    calls: list[str] = []
    monkeypatch.setattr(supervisor, "resume", lambda: calls.append("resume"))
    monkeypatch.setattr(supervisor, "_stop_worker", lambda: calls.append("stop"))
    monkeypatch.setattr(supervisor, "_spawn", lambda mode: calls.append(mode) or {})
    result = supervisor.restore_business()
    assert calls == ["stop", "business"]
    assert result["service_restarted"] is True


def test_supervised_ordinary_web_starts_when_environment_is_not_manageable(
    managed: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module("sqlseed_web.supervisor")
    supervisor = module.Supervisor(port=0)
    supervisor.manager = managed[0]
    supervisor.manager.stop()
    supervisor.manager.environment = replace(supervisor.manager.environment, reason="平台不支持组件管理。")
    monkeypatch.setattr(
        supervisor.manager, "start", lambda: pytest.fail("unsupported environment cannot acquire a lock")
    )
    modes: list[str] = []
    monkeypatch.setattr(supervisor, "_spawn", lambda mode: modes.append(mode))
    try:
        supervisor.start()
        assert modes == ["business"]
        assert supervisor.manager.status()["available"] is False
    finally:
        supervisor.stop()


def test_initial_business_boot_does_not_admit_a_package_plan(managed: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("sqlseed_web.supervisor")
    supervisor = module.Supervisor(port=0)
    supervisor.manager = managed[0]
    supervisor.manager.stop()

    def boot(mode: str) -> dict[str, Any]:
        with pytest.raises(HTTPException):
            supervisor.manager.plan(module.PlanRequest(component_id="mimesis", action="install"))
        return {}

    monkeypatch.setattr(supervisor, "_spawn", boot)
    try:
        supervisor.start()
        assert supervisor.manager.status()["service_ready"] is True
    finally:
        supervisor.stop()
