"""Read-only facts about the interpreter serving this Web application."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import platform
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata
from typing import Any, Literal

from fastapi import APIRouter, Request

_AI_CONFIG_MODULE = "sqlseed_ai.config"

router = APIRouter(prefix="/api/settings", tags=["settings"])

# The pre-0.2.4 release line lacks the workbench/runtime interfaces. Include
# development builds from this release line for source and wheel validation.
AI_INSTALL_REQUIREMENT = "sqlseed-ai>=0.2.4.dev0"


@dataclass(frozen=True)
class _ComponentInfo:
    category: Literal["application", "extension", "provider"]
    requirement: Literal["required", "optional", "builtin"]
    dependency_ids: tuple[str, ...]
    description: str
    install_requirement: str | None
    guidance: str


# These relationships describe the displayed components, not every transitive Python dependency.
_COMPONENTS = {
    "core": _ComponentInfo(
        "application",
        "required",
        ("faker",),
        "离线生成、约束处理与数据库写入",
        "sqlseed",
        "当前应用必需；Faker 是 Core 的必需依赖。",
    ),
    "web": _ComponentInfo(
        "application",
        "required",
        ("core",),
        "当前浏览器工作台",
        "sqlseed-web",
        "当前 Web 应用；安装时会同时安装 Core。",
    ),
    "ai": _ComponentInfo(
        "extension",
        "optional",
        ("core", "cli"),
        "根据表结构与业务说明提出规则建议",
        "sqlseed-web[ai]",
        "可选 AI 扩展；安装时会同时安装 Core 和 CLI。",
    ),
    "cli": _ComponentInfo(
        "extension",
        "optional",
        ("core",),
        "在终端配置、预览和生成数据",
        "sqlseed-cli",
        "基础 Web 功能无需 CLI；安装 AI 扩展时会一并安装。",
    ),
    "mcp": _ComponentInfo(
        "extension",
        "optional",
        ("core",),
        "供 MCP 客户端调用规则生成与填充能力",
        "mcp-server-sqlseed",
        "供 MCP 客户端使用；依赖 Core，无需 AI 或 CLI。",
    ),
    "base": _ComponentInfo(
        "provider",
        "builtin",
        ("core",),
        "内置基础数据与语义占位值",
        None,
        "随 Core 内置，无需单独安装。",
    ),
    "faker": _ComponentInfo(
        "provider",
        "required",
        (),
        "姓名、地址等本地化测试数据",
        "Faker>=30.0",
        "sqlseed 的必需依赖，随 sqlseed 安装。",
    ),
    "mimesis": _ComponentInfo(
        "provider",
        "optional",
        (),
        "另一种本地化数据实现，可按场景选择",
        "sqlseed[mimesis]",
        "按需安装的生成引擎；未安装时仍可使用 Base 和 Faker。",
    ),
}


@dataclass(frozen=True)
class _Installer:
    tool: Literal["pip", "uv"] | None
    python_executable: str
    tool_executable: str | None
    shell: Literal["posix", "powershell"]

    def command(self, action: Literal["install", "check"], requirement: str | None = None) -> str | None:
        """Build a shell-quoted command for the serving interpreter without executing it."""
        if self.tool is None or not self.python_executable or (action == "install" and requirement is None):
            return None
        if self.tool == "pip":
            arguments = [self.python_executable, "-m", "pip", action]
        elif self.tool_executable is not None:
            arguments = [self.tool_executable, "pip", action, "--python", self.python_executable]
        else:
            return None
        if requirement is not None:
            arguments.append(requirement)
        if self.shell == "powershell":
            return "& " + " ".join("'" + argument.replace("'", "''") + "'" for argument in arguments)
        return shlex.join(arguments)

    def public_info(self) -> dict[str, Any]:
        """Describe the detected tool and target interpreter for the settings UI."""
        return {
            "tool": self.tool,
            "shell": self.shell,
            "python_executable": self.python_executable,
            "available": self.tool is not None,
            "message": (
                "命令针对当前 Web 使用的 Python 解释器；完成后重启 Web 服务。"
                if self.tool is not None
                else "未检测到可用的 pip 或 uv。请使用创建此 Python 环境的工具安装或修复组件，完成后重启 Web 服务。"
            ),
        }


@lru_cache(maxsize=32)
def _probe_version(arguments: tuple[str, ...], time_slot: int) -> bool:
    """Cache bounded, read-only version probes for at most 30 seconds."""
    try:
        result = subprocess.run(
            list(arguments),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _installer() -> _Installer:
    executable = sys.executable
    shell: Literal["posix", "powershell"] = "powershell" if sys.platform == "win32" else "posix"
    time_slot = int(time.monotonic() // 30)
    if executable:
        try:
            has_pip = importlib.util.find_spec("pip") is not None
        except (ImportError, ValueError):
            has_pip = False
        if has_pip and _probe_version((executable, "-m", "pip", "--version"), time_slot):
            return _Installer("pip", executable, None, shell)
        uv = shutil.which("uv")
        if uv and _probe_version((uv, "--version"), time_slot):
            return _Installer("uv", executable, uv, shell)
    return _Installer(None, executable, None, shell)


class ComponentMetadataError(RuntimeError):
    """An installed distribution has unreadable or invalid metadata."""


def _component_version(distribution: str) -> str:
    """Normalize metadata-provider failures before capability decisions."""
    try:
        version = metadata.version(distribution)
        if not isinstance(version, str) or not version.strip():
            raise ValueError("Distribution version is missing")
    except metadata.PackageNotFoundError:
        raise
    except Exception as exc:
        raise ComponentMetadataError(f"Unable to read distribution metadata: {distribution}") from exc
    return version


def _load_component(distribution: str, module: str) -> None:
    """Optional module initialization has the same ImportError contract as missing code."""
    try:
        importlib.import_module(module)
        if distribution == "sqlseed-ai":
            _require_ai_contract()
    except Exception as exc:
        raise ImportError(f"Unable to initialize component: {distribution}") from exc


def ai_import_failure() -> dict[str, Any]:
    """Describe a caught AI import failure without exposing dependency exception text."""
    status = "import_error"
    try:
        _component_version("sqlseed-ai")
    except metadata.PackageNotFoundError:
        status = "not_installed"
    except ComponentMetadataError:
        status = "import_error"
    installer = _installer()
    message = (
        "尚未安装 AI 插件，AI 服务检测与规则分析不可用。请在设置的插件页安装 AI；手动配置与生成仍可使用。"
        if status == "not_installed"
        else "AI 插件加载异常或版本不兼容，AI 服务检测与规则分析不可用。请在插件页查看修复指引，确认有可安装的兼容版本后再卸载重装。"
    )
    return {
        "available": False,
        "code": "ai_unavailable",
        "component_id": "ai",
        "recovery_action": "install" if status == "not_installed" else "repair",
        "availability_status": status,
        "message": message,
        "reason": message,
        "installer": installer.public_info(),
        "install_command": installer.command("install", "sqlseed-web[ai]"),
        "repair_command": installer.command("check"),
    }


def _require_ai_contract() -> None:
    """Check interfaces without creating clients, reading settings or calling a model."""
    config = importlib.import_module(_AI_CONFIG_MODULE).AIConfig
    if not {"tool_calling_protocol", "log_llm_interactions"}.issubset(config.model_fields):
        raise ImportError("AI configuration interface is incompatible")
    analyzer = importlib.import_module("sqlseed_ai.analyzer").SchemaAnalyzer
    inspect.signature(analyzer.call_llm).bind(None, [], stage="workbench-suggestions")
    runtime = importlib.import_module("sqlseed_ai.runtime")
    if not all(
        callable(getattr(runtime, factory, None))
        for factory in ("build_ai_config", "build_llm_client", "build_heal_orchestrator")
    ):
        raise ImportError("AI runtime interface is incompatible")


def package_availability(distribution: str, module: str, *, metadata_only: bool = False) -> dict[str, Any]:
    """Web capability requires installed metadata as well as importable code.

    An old sys.modules cache or editable source path inherited by spawn cannot
    re-enable a distribution that the user has explicitly uninstalled.
    """
    installed = metadata_valid = True
    try:
        version = _component_version(distribution)
    except metadata.PackageNotFoundError:
        version, installed, metadata_valid = None, False, False
    except ComponentMetadataError:
        version, metadata_valid = None, False
    available = False
    if metadata_valid and not metadata_only:
        try:
            _load_component(distribution, module)
            available = True
        except ImportError:
            available = False
    if not installed:
        status = "not_installed"
    elif metadata_only:
        status = "installed"
    elif available:
        status = "available"
    else:
        status = "import_error"
    messages = {
        "installed": "已安装；服务恢复后验证运行状态",
        "available": "当前 Python 环境已安装且可导入",
        "import_error": "已安装，但加载失败或版本不兼容；请在插件页查看修复指引",
        "not_installed": "当前 Python 环境未安装；请在插件页安装后使用",
    }
    return {
        "version": version,
        "installed": installed,
        "available": available,
        "status": status,
        "message": messages[status],
    }


def require_ai_available() -> None:
    if not package_availability("sqlseed-ai", _AI_CONFIG_MODULE)["available"]:
        raise ImportError("AI component is unavailable")


def provider_availability() -> dict[str, dict[str, Any]]:
    return {
        "base": package_availability("sqlseed", "sqlseed.generators.base_provider"),
        "faker": package_availability("Faker", "faker"),
        "mimesis": package_availability("mimesis", "mimesis"),
    }


def _package(
    identifier: str,
    name: str,
    distribution: str,
    module: str,
    installer: _Installer,
    *,
    metadata_only: bool = False,
) -> dict[str, Any]:
    info = _COMPONENTS[identifier]
    availability = package_availability(distribution, module, metadata_only=metadata_only)
    status = availability["status"]
    guidance = info.guidance
    if status == "import_error":
        guidance += " 加载异常，请检查运行 Web 的 Python 环境依赖，修复后重启服务。"
    elif status == "not_installed":
        if info.requirement in {"required", "builtin"}:
            guidance = "必需依赖缺失，请修复运行 Web 的 Python 环境。" + guidance
        else:
            guidance += " 如需使用，请在运行 Web 的 Python 环境中安装，然后重启服务。"
    return {
        "id": identifier,
        "name": name,
        "distribution": distribution,
        **availability,
        "category": info.category,
        "requirement": info.requirement,
        "dependency_ids": list(info.dependency_ids),
        "description": info.description,
        "install_command": installer.command("install", info.install_requirement),
        "repair_command": installer.command("check"),
        "guidance": guidance,
    }


@router.get("/environment")
def environment(request: Request) -> dict[str, Any]:
    """Inspect installed metadata and imports; never query a package registry."""
    installer = _installer()
    metadata_only = request.app.state.metadata_only
    return {
        "inspection": "metadata_only" if metadata_only else "metadata_and_imports",
        "installer": installer.public_info(),
        "python": {"version": platform.python_version(), "implementation": platform.python_implementation()},
        "packages": [
            _package("core", "Core", "sqlseed", "sqlseed", installer, metadata_only=metadata_only),
            _package("web", "Web", "sqlseed-web", "sqlseed_web.app", installer, metadata_only=metadata_only),
            _package("ai", "AI", "sqlseed-ai", _AI_CONFIG_MODULE, installer, metadata_only=metadata_only),
            _package("cli", "CLI", "sqlseed-cli", "sqlseed_cli.main", installer, metadata_only=metadata_only),
            _package(
                "mcp", "MCP", "mcp-server-sqlseed", "mcp_server_sqlseed.server", installer, metadata_only=metadata_only
            ),
        ],
        "providers": [
            _package(
                "base", "Base", "sqlseed", "sqlseed.generators.base_provider", installer, metadata_only=metadata_only
            ),
            _package("faker", "Faker", "Faker", "faker", installer, metadata_only=metadata_only),
            _package("mimesis", "Mimesis", "mimesis", "mimesis", installer, metadata_only=metadata_only),
        ],
    }
