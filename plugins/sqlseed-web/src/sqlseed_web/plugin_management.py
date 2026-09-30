"""Opt-in maintenance API for a fixed set of optional components."""

from __future__ import annotations

import hmac
import ipaddress
import secrets
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from sqlseed_web import plugin_environment, plugin_updates
from sqlseed_web.diagnostics import public_error
from sqlseed_web.messages import MessageRoute
from sqlseed_web.messages import message as tr
from sqlseed_web.plugin_environment import COMPONENT_DISTRIBUTIONS, Environment, EnvironmentLock, InstalledPackage
from sqlseed_web.plugin_process import InstallerCleanupPending, run_installer

router = APIRouter(route_class=MessageRoute, prefix="/api/settings/plugins", tags=["plugin-maintenance"])


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_id: Literal["ai", "cli", "mcp", "mimesis"]
    action: Literal["install", "uninstall", "update"]


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str


class ManagementService(Protocol):
    enabled: bool
    token: str

    def status(self) -> dict[str, Any]: ...
    def plan(self, body: PlanRequest) -> dict[str, Any]: ...
    def execute(self, body: ExecuteRequest) -> dict[str, Any]: ...
    def task_snapshot(self, task_id: str | None = None) -> dict[str, Any]: ...
    def recover(self) -> dict[str, Any]: ...


def _reject(message: str, code: str = "plugin_management_unavailable", status: int = 409) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def guard_request(request: Request, manager: ManagementService) -> None:
    """Check transport-derived client, literal Host, same Origin, and a per-process nonce."""
    hosts = request.headers.getlist("host")
    try:
        parsed = urlsplit(f"//{hosts[0]}") if len(hosts) == 1 else None
        valid_host = parsed is not None and parsed.hostname is not None and _loopback(parsed.hostname)
        valid_host = valid_host and parsed is not None and not parsed.username and not parsed.password
        valid_host = valid_host and parsed is not None and not parsed.path and not parsed.query and not parsed.fragment
        if parsed is not None:
            _ = parsed.port
    except ValueError:
        valid_host = False
    if not valid_host or request.client is None or not _loopback(request.client.host):
        raise _reject(
            tr("backend.plugin_management.plugin_management_is_available_only_from_this"),
            "plugin_management_forbidden",
            403,
        )
    origin = request.headers.get("origin")
    expected = f"{request.url.scheme}://{hosts[0]}"
    if origin is not None and origin != expected:
        raise _reject(
            tr("backend.plugin_management.plugin_management_requests_must_come_from_the"),
            "plugin_management_forbidden",
            403,
        )
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise _reject(
            tr("backend.plugin_management.plugin_management_requests_must_come_from_the"),
            "plugin_management_forbidden",
            403,
        )
    if request.method not in {"GET", "HEAD"}:
        token = request.headers.get("x-sqlseed-management-token", "")
        if origin != expected or not hmac.compare_digest(token, manager.token):
            raise _reject(
                tr("backend.plugin_management.the_plugin_management_request_lacks_valid_page"),
                "plugin_management_forbidden",
                403,
            )


class PluginManager:
    """One reviewable plan and one task, protected for the server lifetime."""

    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self.token = secrets.token_urlsafe(32)
        self.environment = plugin_environment._environment()
        self.restart_required = False
        self._lock = threading.RLock()
        self._environment_lock: EnvironmentLock | None = None
        self._startup_reason: str | None = None
        self._plan: dict[str, Any] | None = None
        self._snapshot: dict[str, InstalledPackage] = {}
        self._task: dict[str, Any] | None = None
        self._worker: threading.Thread | None = None
        self._installer_cleanup: InstallerCleanupPending | None = None

    def start(self) -> None:
        prefix = self.environment.prefix
        if not (prefix / "pyvenv.cfg").is_file() or (not self.enabled and self.environment.reason):
            return
        environment_lock = EnvironmentLock(prefix, exclusive=self.enabled)
        try:
            environment_lock.acquire()
        except (OSError, RuntimeError) as exc:
            if not self.enabled:
                raise RuntimeError(
                    tr("backend.plugin_management.cannot_acquire_the_web_environment_lock_check")
                ) from exc
            self._startup_reason = tr("backend.plugin_management.cannot_acquire_the_maintenance_lock_check_permissions")
            return
        self._environment_lock = environment_lock

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.join()
        self._finish_installer_cleanup()
        if self._environment_lock is not None:
            self._environment_lock.release()
            self._environment_lock = None

    def _reason(self) -> str | None:
        if not self.enabled:
            return tr("backend.plugin_management.this_deployment_is_externally_hosted_and_cannot")
        if self._installer_cleanup is not None:
            return tr("backend.plugin_management.installer_cleanup_has_not_been_confirmed_the")
        if self.restart_required:
            return tr("backend.plugin_management.the_environment_has_changed_stop_maintenance_mode")
        if self._task and self._task["status"] == "running":
            return tr("backend.plugin_management.a_component_operation_is_already_running")
        if self.environment.reason:
            return self.environment.reason
        if self._startup_reason:
            return self._startup_reason
        if self._environment_lock is None:
            return tr("backend.plugin_management.the_maintenance_service_has_not_acquired_the")
        return None

    def status(self) -> dict[str, Any]:
        with self._lock:
            reason = self._reason()
            try:
                components = plugin_environment.package_status(
                    plugin_environment.installed_packages(self.environment.prefix), reason
                )
            except RuntimeError:
                reason = tr("backend.plugin_management.installed_package_metadata_cannot_be_safely_parsed")
                components = []
            args = [self.environment.executable, "-m", "sqlseed_web", "--manage-plugins"]
            command = shlex.join(args)
            if sys.platform == "win32":
                command = "& " + " ".join("'" + arg.replace("'", "''") + "'" for arg in args)
            return {
                "enabled": self.enabled,
                "automatic_lifecycle": False,
                "available": reason is None,
                "reason": reason,
                "maintenance_command": command,
                "python_executable": self.environment.executable,
                "token": self.token if self.enabled else None,
                "restart_required": self.restart_required,
                "active_task": self.task_snapshot() if self._task else None,
                "components": components,
            }

    def plan(self, body: PlanRequest) -> dict[str, Any]:
        with self._lock:
            if reason := self._reason():
                raise _reject(reason)
            environment, packages = self._review_environment()
            update = self._review_action(body, packages)
            reviewed_plan = self._plan_details(body, packages, update)
            # Bind a complete new plan atomically; a rejected review leaves the
            # prior installer identity and snapshot untouched.
            self._snapshot = packages
            self._plan = reviewed_plan
            self.environment = environment
            return {
                key: value for key, value in reviewed_plan.items() if key != "expires_at" and not key.startswith("_")
            }

    def _review_environment(self) -> tuple[Environment, dict[str, InstalledPackage]]:
        environment = plugin_environment._environment()
        if environment.prefix != self.environment.prefix or environment.executable != self.environment.executable:
            raise _reject(tr("backend.plugin_management.the_python_environment_has_changed_review_and"))
        if environment.reason:
            raise _reject(environment.reason)
        try:
            packages = plugin_environment.installed_packages(self.environment.prefix)
        except RuntimeError as exc:
            raise _reject(public_error(exc)) from exc
        return environment, packages

    @staticmethod
    def _review_action(
        body: PlanRequest, packages: dict[str, InstalledPackage]
    ) -> plugin_updates.PreparedUpdate | None:
        distribution = COMPONENT_DISTRIBUTIONS[body.component_id]
        package = packages.get(distribution)
        if body.action == "install" and package is not None:
            raise _reject(tr("backend.plugin_management.this_component_is_already_installed_use_the"))
        if body.action == "uninstall":
            if package is None:
                raise _reject(tr("backend.plugin_management.this_component_is_not_installed"))
            if users := plugin_environment.required_by(distribution, packages):
                raise _reject(
                    tr(
                        "backend.plugin_management.required_by_uninstall_those_optional_components_first",
                        p1=", ".join(users),
                    )
                )
        if body.action != "update":
            return None
        if package is None:
            raise _reject(tr("backend.plugin_management.this_component_is_not_installed_install_it"))
        try:
            return plugin_updates.prepare_update(distribution, packages)
        except ValueError as exc:
            raise _reject(public_error(exc), "plugin_update_blocked") from exc

    @staticmethod
    def _plan_details(
        body: PlanRequest, packages: dict[str, InstalledPackage], update: plugin_updates.PreparedUpdate | None
    ) -> dict[str, Any]:
        distribution = COMPONENT_DISTRIBUTIONS[body.component_id]
        package = packages.get(distribution)
        action_label = {
            "install": tr("backend.plugin_management.install"),
            "uninstall": tr("backend.plugin_management.uninstall"),
            "update": tr("backend.plugin_management.update"),
        }[body.action]
        reviewed_plan: dict[str, Any] = {
            "plan_id": secrets.token_urlsafe(24),
            "component_id": body.component_id,
            "action": body.action,
            "distribution": distribution,
            "version": package.version if package else None,
            "summary": tr(
                "backend.plugin_management.in_the_python_environment_currently_running_web",
                p1=action_label,
                p2=distribution,
            ),
            "warnings": [
                tr("backend.plugin_management.installation_accesses_the_package_source_and_freezes")
                if body.action == "install"
                else tr("backend.plugin_management.only_the_selected_component_is_uninstalled_without"),
                tr("backend.plugin_management.after_success_or_failure_stop_maintenance_mode"),
            ],
            "expires_in": 300,
            "expires_at": time.monotonic() + 300,
        }
        if update is not None:
            reviewed_plan.update(
                target_version=update.package.version,
                dependencies=list(update.dependencies),
                artifact={"filename": update.filename, "sha256": update.sha256, "source": "https://pypi.org"},
                warnings=[
                    tr("backend.plugin_management.only_the_selected_component_is_updated_dependencies"),
                    tr("backend.plugin_management.only_a_verified_official_wheel_is_installed"),
                    tr("backend.plugin_management.after_success_or_failure_stop_maintenance_mode"),
                ],
                _update=update,
            )
        return reviewed_plan

    def execute(self, body: ExecuteRequest) -> dict[str, Any]:
        with self._lock:
            if reason := self._reason():
                raise _reject(reason)
            operation_plan = self._plan
            if (
                operation_plan is None
                or not hmac.compare_digest(operation_plan["plan_id"], body.plan_id)
                or time.monotonic() > operation_plan["expires_at"]
            ):
                raise _reject(tr("backend.plugin_management.this_operation_plan_has_expired_review_and"))
            try:
                current = plugin_environment.installed_packages(self.environment.prefix)
            except RuntimeError as exc:
                raise _reject(public_error(exc)) from exc
            if current != self._snapshot or plugin_environment._environment() != self.environment:
                self._plan = None
                raise _reject(tr("backend.plugin_management.the_python_environment_has_changed_review_and"))
            self._task = {
                "task_id": secrets.token_urlsafe(24),
                "component_id": operation_plan["component_id"],
                "action": operation_plan["action"],
                "status": "running",
                "output": [],
                "message": tr("backend.plugin_management.preparing_the_environment_operation"),
                "restart_required": False,
                "returncode": None,
            }
            self._plan = None
            self._worker = threading.Thread(
                target=self._run, args=(operation_plan, current), daemon=False, name="sqlseed-plugin-install"
            )
            try:
                self._worker.start()
            except RuntimeError:
                self._worker = None
                self._task.update(
                    status="failed", message=tr("backend.plugin_management.cannot_start_the_component_operation")
                )
            return self.task_snapshot()

    def task_snapshot(self, task_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if self._task is None or (task_id is not None and self._task["task_id"] != task_id):
                raise _reject(
                    tr("backend.plugin_management.this_component_operation_was_not_found_task"),
                    "plugin_task_not_found",
                    404,
                )
            return {**self._task, "output": list(self._task["output"])}

    def _output(self, text: str) -> None:
        with self._lock:
            if self._task is not None and len(self._task["output"]) < 200:
                self._task["output"].append(text if len(text) <= 2000 else text[:2000])

    def _installation_arguments(
        self, operation_plan: dict[str, Any], before: dict[str, InstalledPackage], directory: Path
    ) -> list[str]:
        constraints = directory / "constraints.txt"
        constraints.write_text(
            "".join(
                f"{name}=={package.version}\n"
                for name, package in sorted(before.items())
                if operation_plan["action"] != "update" or name != operation_plan["distribution"]
            ),
            encoding="utf-8",
        )
        if operation_plan["action"] != "update":
            return plugin_environment.installer_arguments(
                self.environment, operation_plan["action"], operation_plan["distribution"], constraints
            )
        update = operation_plan.get("_update")
        if not isinstance(update, plugin_updates.PreparedUpdate):
            # This is invalid runtime plan data, retaining the operation's ValueError contract.
            raise ValueError(tr("backend.plugin_management.the_update_plan_lacks_a_verified_package"))  # noqa: TRY004
        self._output(tr("backend.plugin_management.downloading_and_verifying_the_confirmed_update_other"))
        try:
            wheel = plugin_updates.download_update(update, directory)
        except ValueError as exc:
            self._output(public_error(exc))
            raise
        # Network time is outside the metadata snapshot's trust boundary.
        if (
            plugin_environment.installed_packages(self.environment.prefix) != before
            or plugin_environment._environment() != self.environment
        ):
            self._output(tr("backend.plugin_management.the_python_environment_changed_during_download_no"))
            raise ValueError(tr("backend.plugin_management.the_environment_changed_during_download_check_for"))
        return plugin_updates.update_arguments(self.environment, wheel, constraints)

    def _operation_preserved_environment(
        self, operation_plan: dict[str, Any], before: dict[str, InstalledPackage]
    ) -> bool:
        after = plugin_environment.installed_packages(self.environment.prefix)
        target = operation_plan["distribution"]
        expected_target = target in after if operation_plan["action"] == "install" else target not in after
        preserved = all(after.get(name) == package for name, package in before.items() if name != target)
        if isinstance(update := operation_plan.get("_update"), plugin_updates.PreparedUpdate):
            expected_target = after.get(target) == update.package
            preserved = preserved and set(after) == set(before)
        return expected_target and preserved

    def _finish_operation(self, cleanup: ExitStack, succeeded: bool, message: str, result: int | None) -> None:
        cleaned = False
        try:
            cleanup.close()
            cleaned = True
        except OSError:
            # A Windows file lock or permissions failure must not strand the
            # task in running after its installer has already been reaped.
            message = tr("backend.plugin_management.temporary_file_cleanup_failed")
            self._output(message)
        finally:
            with self._lock:
                if self._task is not None:
                    self._task.update(
                        status="succeeded" if succeeded and cleaned else "failed", message=message, returncode=result
                    )

    def _run(self, operation_plan: dict[str, Any], before: dict[str, InstalledPackage]) -> None:
        result = None
        succeeded = False
        message = tr("backend.plugin_management.the_component_operation_failed_check_the_output")
        cleanup = ExitStack()
        try:
            directory = cleanup.enter_context(tempfile.TemporaryDirectory(prefix="sqlseed-plugin-plan-"))
            arguments = self._installation_arguments(operation_plan, before, Path(directory))
            with self._lock:
                self.restart_required = True
                if self._task is not None:
                    self._task.update(
                        restart_required=True,
                        message=tr("backend.plugin_management.the_installer_is_running_wait_for_completion"),
                    )
            if self._environment_lock is None:
                raise RuntimeError(tr("backend.plugin_management.the_environment_lock_is_no_longer_valid"))
            result = run_installer(arguments, self._output, lock_descriptor=self._environment_lock.fileno())
            preserved = self._operation_preserved_environment(operation_plan, before)
            if succeeded := result == 0 and preserved:
                message = tr("backend.plugin_management.component_operation_completed_stop_maintenance_mode_and")
            elif result == 0:
                message = tr("backend.plugin_management.the_installer_exited_but_component_metadata_verification")
        except InstallerCleanupPending as error:
            error.hold(cleanup.pop_all())
            self._installer_cleanup = error
            message = tr("backend.plugin_management.cleanup_pending_retry")
            self._output(message)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            self._output(tr("backend.plugin_management.cannot_complete_the_environment_operation_check_it"))
        finally:
            self._finish_operation(cleanup, succeeded, message, result)

    def _finish_installer_cleanup(self) -> None:
        if self._installer_cleanup is not None:
            self._installer_cleanup.retry()
            self._installer_cleanup = None

    def recover(self) -> dict[str, Any]:
        raise _reject(tr("backend.plugin_management.this_deployment_does_not_support_automatic_service"))


def _manager(request: Request) -> ManagementService:
    manager: ManagementService = request.app.state.plugin_manager
    guard_request(request, manager)
    return manager


@router.get("/management")
def management(request: Request) -> dict[str, Any]:
    return _manager(request).status()


@router.post("/plan")
def plan(body: PlanRequest, request: Request) -> dict[str, Any]:
    return _manager(request).plan(body)


@router.post("/execute", status_code=202)
def execute(body: ExecuteRequest, request: Request) -> dict[str, Any]:
    return _manager(request).execute(body)


@router.get("/tasks/{task_id}")
def task(task_id: str, request: Request) -> dict[str, Any]:
    return _manager(request).task_snapshot(task_id)


@router.post("/recover", status_code=202)
def recover(request: Request) -> dict[str, Any]:
    return _manager(request).recover()
