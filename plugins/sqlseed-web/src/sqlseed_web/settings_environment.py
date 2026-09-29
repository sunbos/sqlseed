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

from sqlseed_web.messages import MessageRoute, message_list
from sqlseed_web.messages import message as tr

_AI_CONFIG_MODULE = "sqlseed_ai.config"

router = APIRouter(route_class=MessageRoute, prefix="/api/settings", tags=["settings"])

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
        tr("backend.settings_environment.offline_generation_constraints_and_database_writes"),
        "sqlseed",
        tr("backend.settings_environment.required_by_this_application_faker_is_a"),
    ),
    "web": _ComponentInfo(
        "application",
        "required",
        ("core",),
        tr("backend.settings_environment.the_current_browser_workbench"),
        "sqlseed-web",
        tr("backend.settings_environment.the_current_web_application_installing_it_also"),
    ),
    "ai": _ComponentInfo(
        "extension",
        "optional",
        ("core", "cli"),
        tr("backend.settings_environment.suggest_rules_from_table_structure_and_business"),
        "sqlseed-web[ai]",
        tr("backend.settings_environment.optional_ai_extension_installing_it_also_installs"),
    ),
    "cli": _ComponentInfo(
        "extension",
        "optional",
        ("core",),
        tr("backend.settings_environment.configure_preview_and_generate_data_in_the"),
        "sqlseed-cli",
        tr("backend.settings_environment.basic_web_features_do_not_require_cli"),
    ),
    "mcp": _ComponentInfo(
        "extension",
        "optional",
        ("core",),
        tr("backend.settings_environment.expose_rule_generation_and_data_filling_to"),
        "mcp-server-sqlseed",
        tr("backend.settings_environment.for_mcp_clients_requires_core_without_ai"),
    ),
    "base": _ComponentInfo(
        "provider",
        "builtin",
        ("core",),
        tr("backend.settings_environment.built_in_basic_values_and_semantic_placeholders"),
        None,
        tr("backend.settings_environment.built_into_core_no_separate_installation_is"),
    ),
    "faker": _ComponentInfo(
        "provider",
        "required",
        (),
        tr("backend.settings_environment.localized_test_data_such_as_names_and"),
        "Faker>=30.0",
        tr("backend.settings_environment.required_by_sqlseed_and_installed_with_it"),
    ),
    "mimesis": _ComponentInfo(
        "provider",
        "optional",
        (),
        tr("backend.settings_environment.an_alternative_localized_data_implementation"),
        "sqlseed[mimesis]",
        tr("backend.settings_environment.an_optional_generation_engine_base_and_faker"),
    ),
}


@dataclass(frozen=True)
class _Installer:
    tool: Literal["pip", "uv"] | None
    python_executable: str
    tool_executable: str | None
    shell: Literal["posix", "powershell"]

    def _arguments(self, action: Literal["install", "check"], requirement: str | None) -> list[str] | None:
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
        return arguments

    def command(self, action: Literal["install", "check"], requirement: str | None = None) -> str | None:
        """Build a shell-quoted command for the serving interpreter without executing it."""
        if (arguments := self._arguments(action, requirement)) is None:
            return None
        if self.shell == "powershell":
            return "& " + " ".join("'" + argument.replace("'", "''") + "'" for argument in arguments)
        return shlex.join(arguments)

    def commands(self, action: Literal["install", "check"], requirement: str | None = None) -> list[dict[str, str]]:
        """Provide explicit shell choices; portable commands require the same activated environment."""
        arguments = self._arguments(action, requirement)
        exact = self.command(action, requirement)
        if arguments is None or exact is None:
            return []
        commands = [
            {
                "shell": self.shell,
                "label": tr("backend.settings_environment.powershell_exact_path")
                if self.shell == "powershell"
                else tr("backend.settings_environment.macos_linux_exact_path"),
                "command": exact,
                "note": tr("backend.settings_environment.targets_the_exact_python_interpreter_running_web"),
            }
        ]
        # cmd expands %variables% even inside quotes, and !variables! when delayed
        # expansion is enabled. Do not offer an unsafe approximation for these paths.
        if self.shell == "powershell" and not any(
            any(character in argument for character in '%!"\r\n') for argument in arguments
        ):
            commands.append(
                {
                    "shell": "cmd",
                    "label": tr("backend.settings_environment.cmd_exact_path"),
                    "command": " ".join('"' + argument + '"' for argument in arguments),
                    "note": tr("backend.settings_environment.run_in_windows_command_prompt_targeting_the"),
                }
            )
        portable = f"python -m pip {action}" if self.tool == "pip" else f"uv pip {action} --python python"
        if requirement is not None:
            portable += f' "{requirement}"'
        commands.append(
            {
                "shell": "environment",
                "label": tr("backend.settings_environment.portable_activated_environment"),
                "command": portable,
                "note": tr("backend.settings_environment.activate_the_environment_running_web_run_python"),
            }
        )
        return commands

    def public_info(self) -> dict[str, Any]:
        """Describe the detected tool and target interpreter for the settings UI."""
        return {
            "tool": self.tool,
            "shell": self.shell,
            "python_executable": self.python_executable,
            "available": self.tool is not None,
            "message": (
                tr("backend.settings_environment.commands_target_the_python_interpreter_running_web")
                if self.tool is not None
                else tr("backend.settings_environment.no_usable_pip_or_uv_was_detected")
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
        tr("backend.settings_environment.the_ai_component_is_not_installed_so")
        if status == "not_installed"
        else tr("backend.settings_environment.the_ai_component_failed_to_load_or")
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
        "install_commands": installer.commands("install", "sqlseed-web[ai]"),
        "repair_commands": installer.commands("check"),
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
        "installed": tr("backend.settings_environment.installed_runtime_availability_will_be_checked_after"),
        "available": tr("backend.settings_environment.installed_and_importable_in_the_current_python"),
        "import_error": tr("backend.settings_environment.installed_but_failed_to_load_or_is"),
        "not_installed": tr("backend.settings_environment.not_installed_in_the_current_python_environment"),
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
        guidance = message_list(
            [guidance, tr("backend.settings_environment.loading_failed_repair_dependencies_in_the_python")], ""
        )
    elif status == "not_installed":
        if info.requirement in {"required", "builtin"}:
            guidance = message_list(
                [tr("backend.settings_environment.a_required_dependency_is_missing_repair_the"), guidance], ""
            )
        else:
            guidance = message_list([guidance, tr("backend.settings_environment.to_use_it_install_it_in_the")], "")
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
        "install_commands": installer.commands("install", info.install_requirement),
        "repair_commands": installer.commands("check"),
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
