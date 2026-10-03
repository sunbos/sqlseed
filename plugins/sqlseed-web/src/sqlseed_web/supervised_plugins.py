"""Package operations with automatic, process-isolated business recovery."""

from __future__ import annotations

import secrets
import subprocess
import threading
from typing import Any, Protocol

from fastapi import HTTPException
from sqlseed._utils.logger import get_logger

from sqlseed_web import plugin_environment
from sqlseed_web.managed_worker import WorkerLifecycleError
from sqlseed_web.messages import message as tr
from sqlseed_web.plugin_environment import InstalledPackage
from sqlseed_web.plugin_management import ExecuteRequest, PlanRequest, PluginManager, _reject

logger = get_logger(__name__)


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
        self.recovery_error: dict[str, Any] | None = None
        self._package_status = "failed"
        self._package_message = tr("backend.supervised_plugins.the_component_operation_did_not_complete")

    def _reason(self) -> str | None:
        if self.phase == "recovery_failed":
            return tr("backend.supervised_plugins.the_application_has_not_resumed_retry_service")
        if self.phase != "ready":
            return tr("backend.supervised_plugins.a_component_operation_is_running_the_application")
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
                recovery_error=dict(self.recovery_error) if self.recovery_error is not None else None,
            )
            return result

    def plan(self, body: PlanRequest) -> dict[str, Any]:
        with self._lock:
            result = super().plan(body)
            warnings = [
                *result["warnings"][:-1],
                tr("backend.supervised_plugins.the_workbench_pauses_briefly_during_the_operation"),
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
            self.recovery_error = None
            self._stage(
                "preparing",
                tr("backend.supervised_plugins.preserving_connections_and_preparing_the_component_operation"),
            )
            return self.task_snapshot()

    def task_snapshot(self, task_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            task = super().task_snapshot(task_id)
            task.update(
                stage=self.phase,
                service_ready=self.phase == "ready",
                restart_required=False,
                recovery_error=dict(self.recovery_error) if self.recovery_error is not None else None,
            )
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
        self._package_message = tr("backend.supervised_plugins.the_component_operation_did_not_complete_the")
        try:
            self.controller.enter_maintenance()
            action_label = {
                "install": tr("backend.supervised_plugins.install"),
                "uninstall": tr("backend.supervised_plugins.uninstall"),
                "update": tr("backend.supervised_plugins.update"),
            }[operation_plan["action"]]
            self._stage("installing", tr("backend.supervised_plugins.component_operation", p1=action_label))
            if plugin_environment.installed_packages(self.environment.prefix) != before:
                raise RuntimeError("environment changed before installation")
            super()._run(operation_plan, before)
            with self._lock:
                if self._task is not None:
                    self._package_status = self._task["status"]
                    self._package_message = (
                        tr("backend.supervised_plugins.the_component_operation_completed_and_the_application")
                        if self._package_status == "succeeded"
                        else tr("backend.supervised_plugins.the_component_operation_failed_the_application_has")
                    )
        except (HTTPException, OSError, RuntimeError, ValueError):
            self._package_status = "failed"
            self._package_message = tr("backend.supervised_plugins.precheck_failed_service_restored")
            self._output(tr("backend.supervised_plugins.the_component_operation_did_not_complete_restoring"))
        finally:
            self._restore()

    def _recovery_failed(
        self, message: str = tr("backend.supervised_plugins.the_application_has_not_resumed_retry_recovery")
    ) -> None:
        with self._lock:
            self.phase = "recovery_failed"
            self.restart_required = False
            if self._task is not None:
                self._task.update(
                    status="failed",
                    message=message,
                    service_ready=False,
                )

    def _restore(self, *, retry_cleanup: bool = False) -> None:
        if self._installer_cleanup is not None:
            try:
                if not retry_cleanup:
                    raise RuntimeError("cleanup must be retried explicitly")
                self._finish_installer_cleanup()
            except (OSError, RuntimeError, subprocess.SubprocessError):
                self._recovery_failed(tr("backend.supervised_plugins.installer_cleanup_has_not_been_confirmed_the"))
                return
        self._stage("restoring", tr("backend.supervised_plugins.restoring_the_application_and_connections"))
        restored = None
        try:
            restored = self.controller.restore_business()
        except (HTTPException, OSError, RuntimeError, ValueError) as exc:
            self._record_recovery_error(exc)
            return
        finally:
            if restored is None:
                self._recovery_failed()
        with self._lock:
            self.phase = "ready"
            self.restart_required = False
            self.service_generation += int(restored.get("service_restarted", True))
            self.session_restore = restored
            self.recovery_error = None
            if self._task is not None:
                self._task.update(
                    status=self._package_status,
                    message=self._package_message,
                    restart_required=False,
                    service_ready=True,
                )

    def _record_recovery_error(self, error: Exception) -> None:
        detail = (
            dict(error.detail)
            if isinstance(error, WorkerLifecycleError)
            else {
                "code": "service_restore_failed",
                "message": tr("backend.supervised_plugins.service_restore_failed"),
            }
        )
        with self._lock:
            self.recovery_error = detail
            self._output(detail["message"])
        # Never serialize exception text: imports and connection restoration
        # can include user credentials even when their type is RuntimeError.
        logger.warning("service_recovery_failed", **{key: value for key, value in detail.items() if key != "message"})

    def recover(self) -> dict[str, Any]:
        with self._lock:
            if self.phase != "recovery_failed":
                raise HTTPException(
                    409,
                    detail={
                        "code": "recovery_not_needed",
                        "message": tr("backend.supervised_plugins.the_service_does_not_need_recovery"),
                    },
                )
            self._stage("restoring", tr("backend.supervised_plugins.retrying_application_recovery"))
            self._worker = threading.Thread(
                target=self._restore, kwargs={"retry_cleanup": True}, daemon=False, name="sqlseed-service-recover"
            )
            try:
                self._worker.start()
            except RuntimeError as exc:
                self.phase = "recovery_failed"
                raise _reject(tr("backend.supervised_plugins.cannot_restore_the_service_yet_retry_shortly")) from exc
            return self.status()
