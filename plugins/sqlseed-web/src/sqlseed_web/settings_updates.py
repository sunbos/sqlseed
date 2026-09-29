"""Explicit, metadata-only PyPI checks for the fixed product component list."""

from __future__ import annotations

import http.client
import json
import threading
import time
from dataclasses import dataclass
from importlib import metadata
from typing import Any

from fastapi import APIRouter
from packaging.utils import (
    InvalidSdistFilename,
    InvalidWheelFilename,
    canonicalize_name,
    parse_sdist_filename,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion, Version
from sqlseed._utils.daemon_task import DaemonTask

from sqlseed_web.messages import MessageRoute

router = APIRouter(route_class=MessageRoute, prefix="/api/settings", tags=["settings"])
_PROJECTS = (
    ("core", "Core", "sqlseed"),
    ("web", "Web", "sqlseed-web"),
    ("ai", "AI", "sqlseed-ai"),
    ("cli", "CLI", "sqlseed-cli"),
    ("mcp", "MCP", "mcp-server-sqlseed"),
    ("mimesis", "Mimesis", "mimesis"),
    ("faker", "Faker", "faker"),
)
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_LOCK = threading.Lock()
_TIMEOUT = 5
_CHECK_TIMEOUT = 11
_MAX_BYTES = 8 * 1024 * 1024


@dataclass
class _VersionCheck:
    task: DaemonTask[tuple[float, dict[str, Any]]]
    deadline: float
    discarded: bool = False


_PENDING: dict[str, _VersionCheck] = {}


def _fetch_index(project: str) -> object:
    # No user-selected host, redirects, cookies, credentials, proxy environment,
    # local version, interpreter path or database information crosses this boundary.
    if project not in {item[2] for item in _PROJECTS}:
        raise ValueError("Unknown project")
    connection = http.client.HTTPSConnection("pypi.org", timeout=_TIMEOUT)
    try:
        connection.request(
            "GET",
            f"/simple/{project}/",
            headers={"Accept": "application/vnd.pypi.simple.v1+json", "User-Agent": "sqlseed-update-check"},
        )
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("Index unavailable")
        content = bytearray()
        deadline = time.monotonic() + _TIMEOUT
        while len(content) <= _MAX_BYTES:
            if time.monotonic() >= deadline:
                raise TimeoutError("Index read timed out")
            # read1 performs at most one buffered/raw read, so a trickling body
            # returns to the deadline check instead of filling a large read(n).
            if not (chunk := response.read1(min(65536, _MAX_BYTES + 1 - len(content)))):
                return json.loads(content)
            content.extend(chunk)
        raise ValueError("Index too large")
    finally:
        connection.close()


def _latest_stable(project: str, payload: object) -> str:
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        raise TypeError("Invalid index")
    versions: set[Version] = set()
    for file in payload["files"]:
        if not isinstance(file, dict) or file.get("yanked", False) is not False:
            continue
        filename = file.get("filename")
        if not isinstance(filename, str):
            continue
        try:
            if filename.endswith(".whl"):
                name, version, _, _ = parse_wheel_filename(filename)
            else:
                name, version = parse_sdist_filename(filename)
        except (InvalidWheelFilename, InvalidSdistFilename, InvalidVersion):
            continue
        if name == canonicalize_name(project) and not (version.is_prerelease or version.is_devrelease or version.local):
            versions.add(version)
    if not versions:
        raise ValueError("No stable release")
    return str(max(versions))


def _failed_version() -> dict[str, Any]:
    return {"latest": None, "checked_at": time.time(), "cached": False, "error": True}


def _read_remote_version(project: str) -> dict[str, Any]:
    """Network workers return values only; a late result must never write the cache."""
    result = _failed_version()
    try:
        result["latest"] = _latest_stable(project, _fetch_index(project))
        result["error"] = False
    except (OSError, ValueError, TypeError, RecursionError, http.client.HTTPException):
        result["error"] = True
    return result


def _timed_remote_version(project: str) -> tuple[float, dict[str, Any]]:
    result = _read_remote_version(project)
    return time.monotonic(), result


def _version_check(project: str, deadline: float) -> dict[str, Any] | _VersionCheck:
    with _LOCK:
        if (cached := _CACHE.get(project)) and cached[0] > time.monotonic():
            return {**cached[1], "cached": True}
        if pending := _PENDING.get(project):
            # A timed-out resolver/header read still owns its slot until its
            # actual thread exits. No repeated click can grow background work.
            if not pending.discarded or not pending.task.wait(0):
                return pending
            del _PENDING[project]
        try:
            task = DaemonTask(lambda: _timed_remote_version(project), name="sqlseed-version-check")
        except RuntimeError:
            result = _failed_version()
            _CACHE[project] = (time.monotonic() + 30, result)
            return result
        pending = _VersionCheck(task, deadline)
        _PENDING[project] = pending
        return pending


def _version_result(project: str, check: dict[str, Any] | _VersionCheck, deadline: float) -> dict[str, Any]:
    if isinstance(check, dict):
        return check
    finished = check.task.wait(max(0, min(deadline, check.deadline) - time.monotonic()))
    with _LOCK:
        if not finished and time.monotonic() < check.deadline:
            # An older caller can join a newer shared check with less time left.
            # Its own budget cannot invalidate work still within the owner's budget.
            return _failed_version()
        check.discarded = check.discarded or not finished
        owns_slot = _PENDING.get(project) is check
        try:
            result = _failed_version()
            if finished and not check.discarded:
                completed_at, received = check.task.result()
                check.discarded = completed_at > check.deadline
                if not check.discarded:
                    result = received
            if owns_slot:
                _CACHE[project] = (time.monotonic() + (30 if result["error"] else 900), result)
            return result
        finally:
            # Even an unexpected worker exception must release a completed slot;
            # it still propagates, but cannot poison every future explicit retry.
            if finished and owns_slot:
                del _PENDING[project]


def _remote_version(project: str) -> dict[str, Any]:
    deadline = time.monotonic() + _CHECK_TIMEOUT
    return _version_result(project, _version_check(project, deadline), deadline)


def _compare(current: str | None, latest: str | None) -> str:
    if latest is None:
        return "failed"
    if current is None:
        return "not_installed"
    try:
        installed, stable = Version(current), Version(latest)
    except InvalidVersion:
        return "unknown"
    if installed < stable:
        return "update_available"
    if installed > stable:
        return "ahead"
    return "current"


@router.post("/updates")
def check_updates() -> dict[str, Any]:
    """Check only on explicit requests; never import or install checked packages."""
    # Start fixed, deduplicated project reads together and share one total wait
    # budget, including DNS and response headers (not covered by socket timeout).
    deadline = time.monotonic() + _CHECK_TIMEOUT
    checks = [_version_check(project, deadline) for _, _, project in _PROJECTS]
    remote = [_version_result(item[2], check, deadline) for item, check in zip(_PROJECTS, checks, strict=True)]
    rows = []
    for (identity, label, project), result in zip(_PROJECTS, remote, strict=True):
        try:
            current = metadata.version(project)
        except metadata.PackageNotFoundError:
            current = None
        rows.append(
            {
                "id": identity,
                "label": label,
                "distribution": project,
                "current": current,
                **result,
                "status": _compare(current, result["latest"]),
            }
        )
    return {"components": rows, "source": "https://pypi.org", "cache_seconds": 900}
