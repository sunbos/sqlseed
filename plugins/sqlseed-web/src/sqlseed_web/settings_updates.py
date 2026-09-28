"""Explicit, metadata-only PyPI checks for the fixed product component list."""

from __future__ import annotations

import http.client
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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

router = APIRouter(prefix="/api/settings", tags=["settings"])
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
_MAX_BYTES = 8 * 1024 * 1024


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
            chunk = response.read1(min(65536, _MAX_BYTES + 1 - len(content)))
            if not chunk:
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


def _remote_version(project: str) -> dict[str, Any]:
    now = time.monotonic()
    cached = _CACHE.get(project)
    if cached and cached[0] > now:
        return {**cached[1], "cached": True}
    result: dict[str, Any] = {"latest": None, "checked_at": time.time(), "cached": False}
    try:
        result["latest"] = _latest_stable(project, _fetch_index(project))
        result["error"] = False
    except (OSError, ValueError, TypeError, http.client.HTTPException):
        result["error"] = True
    _CACHE[project] = (time.monotonic() + (30 if result["error"] else 900), result)
    return result


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
    # Serialize batches, so simultaneous clicks/tabs share the freshly filled cache.
    with _LOCK, ThreadPoolExecutor(max_workers=len(_PROJECTS)) as executor:
        remote = list(executor.map(_remote_version, [item[2] for item in _PROJECTS]))
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
