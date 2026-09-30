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

from sqlseed_web.messages import message as tr
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
    reason: str | None = None
    try:
        configuration = (prefix / "pyvenv.cfg").read_text(encoding="utf-8")
        if re.search(r"include-system-site-packages\s*=\s*true", configuration, re.IGNORECASE):
            reason = tr("backend.plugin_environment.environments_sharing_system_site_packages_cannot_be")
        locations = {
            prefix,
            Path(sysconfig.get_path("purelib")).resolve(),
            Path(sysconfig.get_path("platlib")).resolve(),
        }
        for location in locations:
            if not location.is_relative_to(prefix):
                reason = tr("backend.plugin_environment.the_python_installation_directory_is_outside_the")
            else:
                if (location / "EXTERNALLY-MANAGED").exists():
                    reason = tr("backend.plugin_environment.this_environment_is_externally_managed_use_its")
                if not location.is_dir() or not os.access(location, os.W_OK) or not location.stat().st_mode & 0o222:
                    reason = tr("backend.plugin_environment.this_python_environment_is_not_writable_use")
        if reason is None:
            with tempfile.TemporaryFile(dir=prefix) as probe:
                probe.write(b"sqlseed environment write probe")
                probe.flush()
    except (OSError, UnicodeError):
        reason = tr("backend.plugin_environment.cannot_verify_write_permissions_for_this_python")
    return reason


def _environment() -> Environment:
    prefix = Path(sys.prefix).resolve()
    reason: str | None = None
    if sys.prefix == sys.base_prefix or not (prefix / "pyvenv.cfg").is_file():
        reason = tr("backend.plugin_environment.management_requires_the_independent_virtualenv_running_web")
    elif (prefix / "EXTERNALLY-MANAGED").exists():
        reason = tr("backend.plugin_environment.this_environment_is_externally_managed_use_its")
    else:
        reason = _venv_directory_restriction(prefix)
    installer = _installer()
    if reason is None and installer.tool is None:
        reason = tr("backend.plugin_environment.no_usable_pip_or_uv_in_this")
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
        handle = None
        try:
            if sys.platform == "win32":
                from sqlseed_web._windows_process import open_environment_lock

                descriptor = open_environment_lock(self.path, exclusive=self.exclusive)
                try:
                    handle = os.fdopen(descriptor, "r+b" if self.exclusive else "rb")
                except BaseException:
                    os.close(descriptor)
                    raise
            else:
                import fcntl

                handle = self.path.open("a+b")
                fcntl.flock(handle.fileno(), (fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except OSError as exc:
            if handle is not None:
                handle.close()
            raise RuntimeError(tr("backend.plugin_environment.another_web_process_is_using_this_python")) from exc
        self._file = handle

    def release(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def fileno(self) -> int:
        """Retain this same OS lock in an owned serving child until it exits."""
        if self._file is None:
            raise RuntimeError(tr("backend.plugin_environment.the_environment_lock_is_not_held"))
        return self._file.fileno()


class InheritedEnvironmentLock:
    """Duplicate the file object into the spawning child, never a process-owned byte lock."""

    def __init__(self, descriptor: int) -> None:
        self.descriptor = descriptor

    def __reduce__(self) -> tuple[Any, tuple[Any, ...]]:
        if sys.platform != "win32":
            from multiprocessing.reduction import DupFd

            return _PosixEnvironmentHandle, (DupFd(self.descriptor),)
        import msvcrt
        from multiprocessing.context import get_spawning_popen

        if (spawning := get_spawning_popen()) is None:
            raise RuntimeError("Environment handles can only be transferred while spawning a worker")
        handle = spawning.duplicate_for_child(msvcrt.get_osfhandle(self.descriptor))
        return _WindowsEnvironmentHandle, (handle,)

    def detach(self) -> int:
        raise RuntimeError("The parent cannot detach a worker's environment lock")


class _WindowsEnvironmentHandle:
    def __init__(self, handle: int) -> None:
        self.handle: int | None = handle

    def detach(self) -> int:
        if sys.platform == "win32":
            import msvcrt

            if self.handle is None:
                raise RuntimeError("Environment handle was already detached")
            handle, self.handle = self.handle, None
            try:
                return msvcrt.open_osfhandle(handle, os.O_BINARY | os.O_RDONLY)
            except BaseException:
                from _winapi import CloseHandle

                CloseHandle(handle)
                raise
        raise RuntimeError("A Windows environment handle cannot be restored on this platform")


class _PosixEnvironmentHandle:
    def __init__(self, descriptor: Any) -> None:
        self.descriptor = descriptor

    def detach(self) -> int:
        return int(self.descriptor.detach())


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
        raise RuntimeError(tr("backend.plugin_environment.installed_package_metadata_cannot_be_safely_parsed")) from exc
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
        raise RuntimeError(tr("backend.plugin_environment.no_installation_tool_is_available"))
    requirement = AI_INSTALL_REQUIREMENT if action == "install" and distribution == "sqlseed-ai" else distribution
    return [*args, requirement]


def package_status(packages: dict[str, InstalledPackage], unavailable: str | None) -> list[dict[str, Any]]:
    result = []
    for identifier, distribution in COMPONENT_DISTRIBUTIONS.items():
        package = packages.get(distribution)
        users = required_by(distribution, packages)
        reason = unavailable or (
            tr("backend.plugin_environment.required_by_uninstall_those_optional_components_first", p1=", ".join(users))
            if users
            else None
        )
        update_reason = unavailable
        if not update_reason and package is None:
            update_reason = tr("backend.plugin_environment.install_this_component_first")
        elif not update_reason:
            update_reason = None
        result.append(
            {
                "id": identifier,
                "installed": package is not None,
                "version": package.version if package else None,
                "can_install": not unavailable and package is None,
                "can_uninstall": not unavailable and package is not None and not users,
                "can_update": not unavailable and package is not None,
                "update_reason": update_reason,
                "reason": reason,
                "required_by": users,
            }
        )
    return result
