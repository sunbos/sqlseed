"""Package operations with automatic, process-isolated business recovery."""

from __future__ import annotations

import secrets
import threading
from typing import Any, Protocol

from fastapi import HTTPException

from sqlseed_web import plugin_environment
from sqlseed_web.plugin_environment import InstalledPackage
from sqlseed_web.plugin_management import ExecuteRequest, PlanRequest, PluginManager, _reject


class LifecycleController(Protocol):
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def enter_maintenance(self) -> None: ...
    def restore_business(self) -> dict[str, Any]: ...


class SupervisedPluginManager(PluginManager):
    """Keep task ownership in the parent while serving workers are replaced."""

    def __init__(self, controller: LifecycleController) -> None:
        super().__init__(enabled=True)
        self.controller = controller
        self.instance_id = secrets.token_hex(16)
        self.service_generation = 1
        self.phase = "ready"
        self.session_restore: dict[str, Any] = {}
        self._package_status = "failed"
        self._package_message = "组件操作未完成。"

    def _reason(self) -> str | None:
        if self.phase == "recovery_failed":
            return "业务服务未恢复，请在页面重试恢复服务。"
        if self.phase != "ready":
            return "正在处理组件操作，业务服务将自动恢复。"
        return super()._reason()

    def status(self) -> dict[str, Any]:
        with self._lock:
            result = super().status()
            result.update(
                automatic_lifecycle=True,
                instance_id=self.instance_id,
                phase=self.phase,
                service_generation=self.service_generation,
                service_ready=self.phase == "ready",
                session_restore=dict(self.session_restore),
                restart_required=False,
                maintenance_command=None,
            )
            return result

    def plan(self, body: PlanRequest) -> dict[str, Any]:
        with self._lock:
            result = super().plan(body)
            warnings = [
                "安装固定当前环境与已有组件版本；没有兼容版本或 wheel 时会失败。"
                if body.action == "install"
                else "仅卸载选中的组件，不自动卸载其依赖。重新安装需要软件源提供兼容版本；开发版或本地安装的组件可能无法恢复。",
                "操作期间会短暂暂停工作台；完成后自动恢复服务与可恢复的连接，无需手动重启。",
            ]
            result["warnings"] = warnings
            if self._plan is not None:
                self._plan["warnings"] = warnings
            return result

    def execute(self, body: ExecuteRequest) -> dict[str, Any]:
        with self._lock:
            if reason := self._reason():
                raise _reject(reason)
            self.controller.pause()
            try:
                result = super().execute(body)
            except Exception:
                self.controller.resume()
                raise
            if result["status"] == "failed":
                self.controller.resume()
                return result
            self._stage("preparing", "正在暂存连接并准备组件操作。")
            return self.task_snapshot()

    def task_snapshot(self, task_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            task = super().task_snapshot(task_id)
            task.update(stage=self.phase, service_ready=self.phase == "ready", restart_required=False)
            if self.phase not in {"ready", "recovery_failed"}:
                task["status"] = "running"
            return task

    def _stage(self, stage: str, message: str) -> None:
        with self._lock:
            self.phase = stage
            if self._task is not None:
                self._task.update(
                    stage=stage, status="running", message=message, service_ready=False, restart_required=False
                )

    def _run(self, operation_plan: dict[str, Any], before: dict[str, InstalledPackage]) -> None:
        self._package_status = "failed"
        self._package_message = "组件操作未完成，业务服务已恢复；请检查服务日志后重试。"
        try:
            self.controller.enter_maintenance()
            self._stage("installing", "正在安装组件。" if operation_plan["action"] == "install" else "正在卸载组件。")
            if plugin_environment.installed_packages(self.environment.prefix) != before:
                raise RuntimeError("environment changed before installation")
            super()._run(operation_plan, before)
            with self._lock:
                if self._task is not None:
                    self._package_status = self._task["status"]
                    self._package_message = (
                        "组件操作完成，业务服务已自动恢复。"
                        if self._package_status == "succeeded"
                        else "组件操作失败，业务服务已恢复；请查看输出后重试。"
                    )
        except (HTTPException, OSError, RuntimeError, ValueError):
            self._package_status = "failed"
            self._package_message = "组件操作未完成，业务服务已恢复；环境未通过操作前检查。"
            self._output("组件操作未完成，正在自动恢复业务服务。")
        finally:
            self._restore()

    def _recovery_failed(self) -> None:
        with self._lock:
            self.phase = "recovery_failed"
            self.restart_required = False
            if self._task is not None:
                self._task.update(
                    status="failed",
                    message="业务服务未恢复，请点击重试恢复；不会重复安装或卸载。",
                    service_ready=False,
                )

    def _restore(self) -> None:
        self._stage("restoring", "正在恢复业务服务与连接。")
        restored = None
        try:
            restored = self.controller.restore_business()
        except (HTTPException, OSError, RuntimeError, ValueError):
            return
        finally:
            if restored is None:
                self._recovery_failed()
        with self._lock:
            self.phase = "ready"
            self.restart_required = False
            self.service_generation += int(restored.get("service_restarted", True))
            self.session_restore = restored
            if self._task is not None:
                self._task.update(
                    status=self._package_status,
                    message=self._package_message,
                    restart_required=False,
                    service_ready=True,
                )

    def recover(self) -> dict[str, Any]:
        with self._lock:
            if self.phase != "recovery_failed":
                raise HTTPException(409, detail={"code": "recovery_not_needed", "message": "当前服务无需恢复。"})
            self._stage("restoring", "正在重试恢复业务服务。")
            self._worker = threading.Thread(target=self._restore, daemon=False, name="sqlseed-service-recover")
            try:
                self._worker.start()
            except RuntimeError as exc:
                self.phase = "recovery_failed"
                raise _reject("暂时无法恢复服务，请稍后重试。") from exc
            return self.status()
