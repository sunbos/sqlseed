"""Task finalization survives temporary-file cleanup errors without rerunning installers."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sqlseed_web import plugin_environment, plugin_management
from sqlseed_web.plugin_environment import Environment, EnvironmentLock
from sqlseed_web.supervised_plugins import SupervisedPluginManager


def _remove_test_directories(directories: list[Path], root: Path) -> None:
    for directory in directories:
        assert directory.resolve().parent == root.resolve()
        if directory.exists():
            shutil.rmtree(directory)


@pytest.mark.parametrize("supervised", [False, True])
@pytest.mark.parametrize("returncode", [0, 17])
@pytest.mark.parametrize(
    "locked_file",
    [False, pytest.param(True, marks=pytest.mark.skipif(sys.platform != "win32", reason="Windows share-deny handle"))],
)
def test_cleanup_failure_publishes_terminal_state_and_preserves_environment_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, supervised: bool, returncode: int, locked_file: bool
) -> None:
    prefix = tmp_path / "environment"
    site = prefix / "site-packages"
    site.mkdir(parents=True)
    (prefix / "pyvenv.cfg").write_text("include-system-site-packages = false\n", encoding="utf-8")

    def install_metadata(name: str) -> None:
        directory = site / f"{name}-1.0.dist-info"
        directory.mkdir()
        (directory / "METADATA").write_text(f"Name: {name}\nVersion: 1.0\n", encoding="utf-8")

    for name in ("sqlseed", "sqlseed-web", "Faker"):
        install_metadata(name)
    monkeypatch.setattr(
        plugin_environment, "_environment", lambda: Environment(prefix, sys.executable, "pip", None, None)
    )
    monkeypatch.setattr(plugin_environment, "_distribution_paths", lambda: [str(site)])
    phases: list[str] = []
    controller = SimpleNamespace(
        pause=lambda: phases.append("pause"),
        resume=lambda: phases.append("resume"),
        enter_maintenance=lambda: phases.append("maintenance"),
        restore_business=lambda: phases.append("restore") or {"restored_connections": 0},
    )
    manager = SupervisedPluginManager(controller) if supervised else plugin_management.PluginManager(enabled=True)
    temporary_directory = tempfile.TemporaryDirectory
    descriptors: list[int] = []
    directories: list[Path] = []
    calls: list[list[str]] = []

    class CleanupFailure(temporary_directory):
        def cleanup(self) -> None:
            super().cleanup()
            if not locked_file:
                raise PermissionError("secret-token=do-not-expose private temporary path")

    monkeypatch.setattr(
        plugin_management.tempfile, "TemporaryDirectory", lambda **kwargs: CleanupFailure(dir=tmp_path, **kwargs)
    )

    def installer(arguments: list[str], output: Any, **kwargs: Any) -> int:
        calls.append(arguments)
        constraints = Path(arguments[arguments.index("--constraint") + 1])
        directories.append(constraints.parent)
        if locked_file:
            from sqlseed_web._windows_process import open_environment_lock

            descriptors.append(open_environment_lock(constraints, exclusive=True))
        if returncode == 0:
            install_metadata("mimesis")
        return returncode

    monkeypatch.setattr(plugin_management, "run_installer", installer)
    manager.start()
    try:
        plan = manager.plan(plugin_management.PlanRequest(component_id="mimesis", action="install"))
        task = manager.execute(plugin_management.ExecuteRequest(plan_id=plan["plan_id"]))
        manager._worker.join(5)
        assert not manager._worker.is_alive()
        result = manager.task_snapshot(task["task_id"])
        assert result["status"] == "failed"
        assert result["returncode"] == returncode
        assert len(calls) == 1
        assert any(
            message.key == "backend.plugin_management.temporary_file_cleanup_failed" for message in result["output"]
        )
        assert "do-not-expose" not in str(result)
        assert "private temporary path" not in str(result)
        with pytest.raises(RuntimeError):
            EnvironmentLock(prefix, exclusive=True).acquire()
        if supervised:
            assert result["service_ready"] is True
            assert phases == ["pause", "maintenance", "restore"]
            assert manager.status()["phase"] == "ready"
        else:
            assert result["restart_required"] is True
            assert result["message"].key == "backend.plugin_management.temporary_file_cleanup_failed"
            assert not phases
        assert ("mimesis" in plugin_environment.installed_packages(prefix)) is (returncode == 0)
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
        manager.stop()
        _remove_test_directories(directories, tmp_path)
    contender = EnvironmentLock(prefix, exclusive=True)
    contender.acquire()
    contender.release()
