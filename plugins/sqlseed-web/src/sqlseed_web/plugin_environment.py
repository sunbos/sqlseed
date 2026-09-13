"""Interpreter-bound package metadata and lifetime environment admission."""

from __future__ import annotations

import os
import re
import sys
import sysconfig
import tempfile
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import IO, Any

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from sqlseed_web.settings_environment import AI_INSTALL_REQUIREMENT, _installer

COMPONENT_DISTRIBUTIONS = {
    "ai": "sqlseed-ai",
    "cli": "sqlseed-cli",
    "mcp": "mcp-server-sqlseed",
    "mimesis": "mimesis",
}


@dataclass(frozen=True)
class Environment:
    """A server-owned target; none of these fields are accepted from HTTP."""

    prefix: Path
    executable: str
    tool: str | None
    tool_executable: str | None
    reason: str | None


def _venv_directory_restriction(prefix: Path) -> str | None:
    """Check isolation and write access, retaining the last applicable restriction."""
    reason = None
    try:
        configuration = (prefix / "pyvenv.cfg").read_text(encoding="utf-8")
        if re.search(r"include-system-site-packages\s*=\s*true", configuration, re.IGNORECASE):
            reason = "共享系统 site-packages 的环境不支持界面管理。"
        locations = {
            prefix,
            Path(sysconfig.get_path("purelib")).resolve(),
            Path(sysconfig.get_path("platlib")).resolve(),
        }
        for location in locations:
            if not location.is_relative_to(prefix):
                reason = "Python 安装目录位于 virtualenv 之外，不支持界面管理。"
            else:
                if (location / "EXTERNALLY-MANAGED").exists():
                    reason = "此环境由外部工具管理，请使用原环境管理工具。"
                if not location.is_dir() or not os.access(location, os.W_OK) or not location.stat().st_mode & 0o222:
                    reason = "当前 Python 环境不可写，请使用原环境管理工具。"
        if reason is None:
            with tempfile.TemporaryFile(dir=prefix) as probe:
                probe.write(b"sqlseed environment write probe")
                probe.flush()
    except (OSError, UnicodeError):
        reason = "无法验证当前 Python 环境的写入权限。"
    return reason


def _environment() -> Environment:
    prefix = Path(sys.prefix).resolve()
    reason = None
    if sys.platform == "win32":
        reason = "Windows 暂不支持界面组件管理；请使用页面提供的 PowerShell 命令手动管理环境。"
    elif sys.prefix == sys.base_prefix or not (prefix / "pyvenv.cfg").is_file():
        reason = "仅支持当前 Web 所在的独立 virtualenv；系统 Python 请使用原环境管理工具。"
    elif (prefix / "EXTERNALLY-MANAGED").exists():
        reason = "此环境由外部工具管理，请使用原环境管理工具。"
    else:
        reason = _venv_directory_restriction(prefix)
    installer = _installer()
    if reason is None and installer.tool is None:
        reason = "当前 Python 环境没有可用的 pip 或 uv；请使用原环境管理工具。"
    return Environment(prefix, sys.executable, installer.tool, installer.tool_executable, reason)


class EnvironmentLock:
    """Shared normal servers and an exclusive maintenance server cannot coexist.

    The lock is held through shutdown, including any package worker. It never
    removes the lock file, preventing old/new inode races between processes.
    """

    def __init__(self, prefix: Path, *, exclusive: bool) -> None:
        self.path = prefix / ".sqlseed-web-environment.lock"
        self.exclusive = exclusive
        self._file: IO[bytes] | None = None

    def acquire(self) -> None:
        if self._file is not None:
            return
        handle = self.path.open("a+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK if self.exclusive else msvcrt.LK_NBRLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), (fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise RuntimeError("另一个 Web 进程正在使用此 Python 环境，请先停止它。") from exc
        self._file = handle

    def release(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def fileno(self) -> int:
        """Retain this same OS lock in an owned serving child until it exits."""
        if self._file is None:
            raise RuntimeError("环境锁尚未持有。")
        return self._file.fileno()


@dataclass(frozen=True)
class InstalledPackage:
    """Validated installed metadata, independent of already imported modules."""

    version: str
    requirements: tuple[str, ...]


def _distribution_paths() -> list[str]:
    return sys.path


def installed_packages(prefix: Path) -> dict[str, InstalledPackage]:
    result: dict[str, InstalledPackage] = {}
    try:
        for distribution in metadata.distributions(path=_distribution_paths()):
            if not Path(str(distribution.locate_file(""))).resolve().is_relative_to(prefix.resolve()):
                raise ValueError("distribution metadata is outside the managed environment")
            name = distribution.metadata["Name"]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
                raise ValueError("invalid distribution name")
            normalized = canonicalize_name(name)
            version = str(Version(distribution.version))
            requirements = tuple(sorted(distribution.requires or []))
            for requirement in requirements:
                Requirement(requirement)
            item = InstalledPackage(version, requirements)
            if normalized in result and result[normalized] != item:
                raise ValueError("conflicting distribution metadata")
            result[normalized] = item
        if not {"sqlseed", "sqlseed-web", "faker"}.issubset(result):
            raise ValueError("required distribution metadata is absent")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("已安装组件的元数据无法安全解析；请先修复当前 Python 环境。") from exc
    return result


def required_by(distribution: str, packages: dict[str, InstalledPackage]) -> list[str]:
    """Only active base requirements block removal; extras are not installed-state facts."""
    result = []
    for name, package in packages.items():
        if name == distribution:
            continue
        for text in package.requirements:
            requirement = Requirement(text)
            if canonicalize_name(requirement.name) == distribution and (
                requirement.marker is None or requirement.marker.evaluate({"extra": ""})
            ):
                result.append(name)
                break
    return sorted(result)


def installer_arguments(environment: Environment, action: str, distribution: str, constraints: Path) -> list[str]:
    """Construct fixed argv with no shell and no configurable target or package."""
    if distribution not in COMPONENT_DISTRIBUTIONS.values() or action not in {"install", "uninstall"}:
        raise ValueError("unsupported component operation")
    if environment.tool == "pip":
        args = [environment.executable, "-m", "pip", "--isolated", action, "--disable-pip-version-check", "--no-input"]
        if action == "install":
            args += ["--constraint", str(constraints), "--only-binary=:all:"]
        else:
            args += ["--yes"]
    elif environment.tool == "uv" and environment.tool_executable:
        args = [
            environment.tool_executable,
            "--no-config",
            "pip",
            action,
            "--python",
            environment.executable,
            "--no-python-downloads",
        ]
        if action == "install":
            args += ["--constraints", str(constraints), "--only-binary=:all:"]
    else:
        raise RuntimeError("没有可用的安装工具。")
    requirement = AI_INSTALL_REQUIREMENT if action == "install" and distribution == "sqlseed-ai" else distribution
    return [*args, requirement]


def package_status(packages: dict[str, InstalledPackage], unavailable: str | None) -> list[dict[str, Any]]:
    result = []
    for identifier, distribution in COMPONENT_DISTRIBUTIONS.items():
        package = packages.get(distribution)
        users = required_by(distribution, packages)
        reason = unavailable or (f"由 {', '.join(users)} 使用，请先卸载这些可选组件。" if users else None)
        result.append(
            {
                "id": identifier,
                "installed": package is not None,
                "version": package.version if package else None,
                "can_install": not unavailable and package is None,
                "can_uninstall": not unavailable and package is not None and not users,
                "reason": reason,
                "required_by": users,
            }
        )
    return result
