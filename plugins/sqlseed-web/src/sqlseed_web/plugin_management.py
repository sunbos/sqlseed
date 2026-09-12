"""Opt-in maintenance API for a fixed set of optional components."""

from __future__ import annotations

import hmac
import ipaddress
import secrets
import shlex
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from sqlseed_web import plugin_environment
from sqlseed_web.plugin_environment import COMPONENT_DISTRIBUTIONS, EnvironmentLock, InstalledPackage
from sqlseed_web.plugin_process import run_installer

router = APIRouter(prefix="/api/settings/plugins", tags=["plugin-maintenance"])


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_id: Literal["ai", "cli", "mcp", "mimesis"]
    action: Literal["install", "uninstall"]


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
        parsed = urlsplit(f"http://{hosts[0]}") if len(hosts) == 1 else None
        valid_host = parsed is not None and parsed.hostname is not None and _loopback(parsed.hostname)
        valid_host = valid_host and parsed is not None and not parsed.username and not parsed.password
        valid_host = valid_host and parsed is not None and not parsed.path and not parsed.query and not parsed.fragment
        if parsed is not None:
            _ = parsed.port
    except ValueError:
        valid_host = False
    if not valid_host or request.client is None or not _loopback(request.client.host):
        raise _reject("插件管理仅允许本机访问。", "plugin_management_forbidden", 403)
    origin = request.headers.get("origin")
    expected = f"{request.url.scheme}://{hosts[0]}"
    if origin is not None and origin != expected:
        raise _reject("插件管理请求必须来自当前页面。", "plugin_management_forbidden", 403)
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise _reject("插件管理请求必须来自当前页面。", "plugin_management_forbidden", 403)
    if request.method not in {"GET", "HEAD"}:
        token = request.headers.get("x-sqlseed-management-token", "")
        if origin != expected or not hmac.compare_digest(token, manager.token):
            raise _reject("插件管理请求缺少有效的页面凭据。", "plugin_management_forbidden", 403)


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

    def start(self) -> None:
        prefix = self.environment.prefix
        if not (prefix / "pyvenv.cfg").is_file() or (not self.enabled and self.environment.reason):
            return
        environment_lock = EnvironmentLock(prefix, exclusive=self.enabled)
        try:
            environment_lock.acquire()
        except (OSError, RuntimeError) as exc:
            if not self.enabled:
                raise RuntimeError("无法领取 Web 环境使用锁；请检查权限或停止正在运行的维护服务。") from exc
            self._startup_reason = "无法领取维护锁；请检查权限并停止使用此环境的其他 Web 进程。"
            return
        self._environment_lock = environment_lock

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.join()
        if self._environment_lock is not None:
            self._environment_lock.release()
            self._environment_lock = None

    def _reason(self) -> str | None:
        if not self.enabled:
            return "此部署由外部服务托管，暂不支持网页安装或卸载；请联系部署管理员。"
        if self.restart_required:
            return "环境已执行变更，请先停止维护服务并正常重启 Web 验证。"
        if self._task and self._task["status"] == "running":
            return "已有组件操作正在执行。"
        if self.environment.reason:
            return self.environment.reason
        if self._startup_reason:
            return self._startup_reason
        if self._environment_lock is None:
            return "维护服务尚未领取环境锁。"
        return None

    def status(self) -> dict[str, Any]:
        with self._lock:
            reason = self._reason()
            try:
                components = plugin_environment.package_status(
                    plugin_environment.installed_packages(self.environment.prefix), reason
                )
            except RuntimeError:
                reason = "已安装组件的元数据无法安全解析；请先修复当前 Python 环境。"
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
            try:
                packages = plugin_environment.installed_packages(self.environment.prefix)
            except RuntimeError as exc:
                raise _reject(str(exc)) from exc
            distribution = COMPONENT_DISTRIBUTIONS[body.component_id]
            package = packages.get(distribution)
            if body.action == "install" and package is not None:
                raise _reject("此组件已经安装；加载异常请使用修复指引。")
            if body.action == "uninstall":
                if package is None:
                    raise _reject("此组件尚未安装。")
                users = plugin_environment.required_by(distribution, packages)
                if users:
                    raise _reject(f"由 {', '.join(users)} 使用，请先卸载这些可选组件。")
            self._snapshot = packages
            self._plan = {
                "plan_id": secrets.token_urlsafe(24),
                "component_id": body.component_id,
                "action": body.action,
                "distribution": distribution,
                "version": package.version if package else None,
                "summary": f"{'安装' if body.action == 'install' else '卸载'} {distribution}，目标是当前 Web 的 Python 环境。",
                "warnings": [
                    "安装会访问软件包源，并冻结所有已安装组件的版本；不兼容时失败，不自动升级。"
                    if body.action == "install"
                    else "仅卸载选中的组件，不自动卸载其依赖。重新安装需要软件源提供兼容版本；开发版或本地安装的组件可能无法恢复。",
                    "完成或失败后均需停止维护服务，正常重启 Web 并检查组件状态。",
                ],
                "expires_in": 300,
                "expires_at": time.monotonic() + 300,
            }
            return {key: value for key, value in self._plan.items() if key != "expires_at"}

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
                raise _reject("操作计划已失效，请重新查看并确认。")
            try:
                current = plugin_environment.installed_packages(self.environment.prefix)
            except RuntimeError as exc:
                raise _reject(str(exc)) from exc
            if current != self._snapshot or plugin_environment._environment() != self.environment:
                self._plan = None
                raise _reject("Python 环境已发生变化，请重新查看并确认操作计划。")
            self._task = {
                "task_id": secrets.token_urlsafe(24),
                "component_id": operation_plan["component_id"],
                "action": operation_plan["action"],
                "status": "running",
                "output": [],
                "message": "正在准备环境操作。",
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
                self._task.update(status="failed", message="无法启动组件操作。")
            return self.task_snapshot()

    def task_snapshot(self, task_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if self._task is None or (task_id is not None and self._task["task_id"] != task_id):
                raise _reject("找不到此组件操作；服务重启后任务记录不再保留。", "plugin_task_not_found", 404)
            return {**self._task, "output": list(self._task["output"])}

    def _output(self, text: str) -> None:
        with self._lock:
            if self._task is not None and len(self._task["output"]) < 200:
                self._task["output"].append(text[:2000])

    def _run(self, operation_plan: dict[str, Any], before: dict[str, InstalledPackage]) -> None:
        result = None
        succeeded = False
        message = "组件操作失败；请检查输出并使用原环境管理工具修复。"
        try:
            with tempfile.TemporaryDirectory(prefix="sqlseed-plugin-plan-") as directory:
                constraints = Path(directory) / "constraints.txt"
                constraints.write_text(
                    "".join(f"{name}=={package.version}\n" for name, package in sorted(before.items())),
                    encoding="utf-8",
                )
                arguments = plugin_environment.installer_arguments(
                    self.environment, operation_plan["action"], operation_plan["distribution"], constraints
                )
                with self._lock:
                    self.restart_required = True
                    if self._task is not None:
                        self._task.update(restart_required=True, message="安装工具正在运行，请等待完成。")
                if self._environment_lock is None:
                    raise RuntimeError("环境锁已失效，未执行安装工具。")
                result = run_installer(arguments, self._output, lock_descriptor=self._environment_lock.fileno())
                after = plugin_environment.installed_packages(self.environment.prefix)
                target = operation_plan["distribution"]
                expected_target = target in after if operation_plan["action"] == "install" else target not in after
                preserved = all(after.get(name) == package for name, package in before.items() if name != target)
                succeeded = result == 0 and expected_target and preserved
                if succeeded:
                    message = "组件操作完成；请停止维护服务并正常重启 Web 验证。"
                elif result == 0:
                    message = "安装工具已退出，但组件元数据核验未通过；请检查环境并重启 Web。"
        except Exception:  # noqa: BLE001
            # The package-task boundary must publish a terminal result without exposing tool errors.
            # Process/tool paths and arbitrary exceptions may contain credentials.
            self._output("无法完成环境操作；请使用原环境管理工具检查。")
        finally:
            with self._lock:
                if self._task is not None:
                    self._task.update(status="succeeded" if succeeded else "failed", message=message, returncode=result)

    def recover(self) -> dict[str, Any]:
        raise _reject("此部署不支持自动恢复服务。")


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
