"""Review one compatible optional-component wheel without changing dependencies."""

from __future__ import annotations

import hashlib
import http.client
import re
import sys
import threading
import time
import zipfile
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import compat32
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlsplit

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.tags import Tag, sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import InvalidVersion, Version
from sqlseed._utils.daemon_task import DaemonTask

from sqlseed_web import settings_updates
from sqlseed_web.messages import message as tr
from sqlseed_web.messages import message_list
from sqlseed_web.plugin_environment import COMPONENT_DISTRIBUTIONS, Environment, InstalledPackage
from sqlseed_web.settings_environment import AI_INSTALL_REQUIREMENT

_MAX_METADATA = 1024 * 1024
_MAX_WHEEL = 64 * 1024 * 1024
_PLAN_TIMEOUT = 11
_DOWNLOAD_TIMEOUT = 35
_NETWORK_SLOT = threading.BoundedSemaphore(1)
_T = TypeVar("_T")


@contextmanager
def _network_slot() -> Iterator[None]:
    """Reserve admission without blocking; the owner releases it on exit."""
    if not _NETWORK_SLOT.acquire(blocking=False):
        raise ValueError(tr("backend.plugin_updates.the_previous_update_check_is_still_finishing"))
    try:
        yield
    finally:
        _NETWORK_SLOT.release()


def _bounded_network(operation: Callable[[], _T], timeout: float) -> _T:
    # Transfer ownership before starting the thread. A caller timeout cannot
    # release admission while DNS/headers or the download are still running.
    with ExitStack() as admission:
        admission.enter_context(_network_slot())
        worker_resources = admission.pop_all()

    def run() -> _T:
        with worker_resources:
            return operation()

    try:
        task = DaemonTask(run, name="sqlseed-update-read")
    except RuntimeError:
        worker_resources.close()
        raise
    if not task.wait(timeout):
        raise ValueError(tr("backend.plugin_updates.the_update_check_or_download_timed_out"))
    return task.result()


@dataclass(frozen=True)
class PreparedUpdate:
    distribution: str
    filename: str
    url: str
    sha256: str
    metadata_sha256: str
    package: InstalledPackage
    dependencies: tuple[str, ...]


def _artifact_path(url: str) -> str:
    parsed = urlsplit(url)
    trusted_origin = parsed.scheme == "https" and parsed.netloc == "files.pythonhosted.org"
    package_path = parsed.path.startswith("/packages/") and not parsed.query and not parsed.fragment
    if not trusted_origin or not package_path or any(character.isspace() for character in url):
        raise ValueError(tr("backend.plugin_updates.the_package_download_address_is_not_a"))
    return parsed.path


def _read_artifact(url: str, *, limit: int, timeout: float) -> bytes:
    path = _artifact_path(url)
    connection = http.client.HTTPSConnection("files.pythonhosted.org", timeout=timeout)
    deadline = time.monotonic() + timeout
    try:
        connection.request("GET", path, headers={"User-Agent": "sqlseed-component-update"})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(tr("backend.plugin_updates.the_official_package_is_temporarily_unavailable_retry"))
        content = bytearray()
        while len(content) <= limit:
            if (remaining := deadline - time.monotonic()) <= 0:
                raise TimeoutError("Package read timed out")
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            if not (chunk := response.read1(min(65536, limit + 1 - len(content)))):
                return bytes(content)
            content.extend(chunk)
        raise ValueError(tr("backend.plugin_updates.the_package_exceeds_the_size_limit_for"))
    finally:
        connection.close()


def _package_metadata(data: bytes, distribution: str, version: str) -> InstalledPackage:
    message = BytesParser(policy=compat32).parsebytes(data)
    if (
        len(message.get_all("Name", [])) != 1
        or len(message.get_all("Version", [])) != 1
        or canonicalize_name(str(message["Name"])) != distribution
        or Version(str(message["Version"])) != Version(version)
    ):
        raise ValueError(tr("backend.plugin_updates.package_metadata_does_not_match_the_selected"))
    python_requirement = message.get("Requires-Python")
    if python_requirement and not SpecifierSet(str(python_requirement)).contains(
        ".".join(str(part) for part in sys.version_info[:3])
    ):
        raise ValueError(tr("backend.plugin_updates.the_latest_stable_version_does_not_support"))
    requirements = tuple(sorted(str(value) for value in message.get_all("Requires-Dist", [])))
    for requirement in requirements:
        Requirement(requirement)
    return InstalledPackage(str(Version(version)), requirements)


def dependency_conflicts(packages: dict[str, InstalledPackage]) -> tuple[list[str], tuple[str, ...]]:
    """Check active base and requested-extra edges, including reverse dependencies."""
    issues: set[str] = set()
    dependencies: set[str] = set()
    pending = [(name, "") for name in packages]
    seen: set[tuple[str, str]] = set()
    while pending:
        name, extra = pending.pop()
        if (name, extra) in seen:
            continue
        seen.add((name, extra))
        for text in packages[name].requirements:
            requirement = Requirement(text)
            if requirement.marker is not None and not requirement.marker.evaluate({"extra": extra}):
                continue
            target = canonicalize_name(requirement.name)
            installed = packages.get(target)
            if requirement.url:
                issues.add(
                    tr("backend.plugin_updates.requires_a_specific_source_for_compatibility_cannot", p1=name, p2=target)
                )
            elif installed is None:
                issues.add(
                    tr("backend.plugin_updates.requires_not_installed", p1=name, p2=target, p3=requirement.specifier)
                )
            elif not requirement.specifier.contains(installed.version, prereleases=True):
                issues.add(
                    tr(
                        "backend.plugin_updates.requires_installed",
                        p1=name,
                        p2=target,
                        p3=requirement.specifier,
                        p4=installed.version,
                    )
                )
            else:
                dependencies.add(f"{target}=={installed.version}")
                pending.extend((target, requested) for requested in requirement.extras)
    return sorted(issues), tuple(sorted(dependencies))


def prepare_update(distribution: str, packages: dict[str, InstalledPackage]) -> PreparedUpdate:
    if distribution not in COMPONENT_DISTRIBUTIONS.values() or distribution not in packages:
        raise ValueError(tr("backend.plugin_updates.only_installed_optional_components_can_be_updated"))
    return _bounded_network(lambda: _prepare_update(distribution, dict(packages)), _PLAN_TIMEOUT)


def _wheel_rank(file: dict[str, Any], distribution: str, latest: Version, tags: dict[Tag, int]) -> int | None:
    """Rank compatible wheels by interpreter tags, rejecting unverified metadata."""
    filename = file.get("filename", "")
    if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", filename):
        return None
    try:
        name, version, _, wheel_tags = parse_wheel_filename(filename)
    except ValueError:
        return None
    if name != distribution or version != latest or not wheel_tags.intersection(tags):
        return None
    required_python = file.get("requires-python")
    if required_python and not SpecifierSet(required_python).contains(".".join(str(p) for p in sys.version_info[:3])):
        return None
    if not file.get("core-metadata", file.get("dist-info-metadata")):
        return None
    return min(tags[tag] for tag in wheel_tags if tag in tags)


def _select_wheel(payload: object, distribution: str, latest: str) -> dict[str, Any]:
    """Choose the highest-priority wheel with a stable filename tie-breaker."""
    if not isinstance(payload, dict):
        raise TypeError(tr("backend.plugin_updates.the_official_index_has_an_invalid_format"))
    candidates: list[tuple[int, dict[str, Any]]] = []
    tags = {tag: index for index, tag in enumerate(sys_tags())}
    version = Version(latest)
    for file in payload["files"]:
        if not isinstance(file, dict) or file.get("yanked", False) is not False:
            continue
        if (rank := _wheel_rank(file, distribution, version, tags)) is not None:
            candidates.append((rank, file))
    if not candidates:
        raise ValueError(tr("backend.plugin_updates.no_wheel_for_the_latest_stable_version"))
    return min(candidates, key=lambda item: (item[0], item[1]["filename"]))[1]


def _prepare_update(distribution: str, packages: dict[str, InstalledPackage]) -> PreparedUpdate:
    try:
        payload = settings_updates._fetch_index(distribution)
        latest = settings_updates._latest_stable(distribution, payload)
        if Version(latest) <= Version(packages[distribution].version):
            raise ValueError(tr("backend.plugin_updates.the_installed_version_is_already_at_or"))
        if distribution == "sqlseed-ai" and not Requirement(AI_INSTALL_REQUIREMENT).specifier.contains(latest):
            raise ValueError(tr("backend.plugin_updates.the_latest_stable_version_does_not_meet"))
        candidate = _select_wheel(payload, distribution, latest)
        url, filename = str(candidate["url"]), str(candidate["filename"])
        _artifact_path(url)
        digest = candidate.get("hashes", {}).get("sha256", "")
        if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError(tr("backend.plugin_updates.the_official_package_lacks_a_valid_sha256"))
        data = _read_artifact(url + ".metadata", limit=_MAX_METADATA, timeout=5)
        metadata_digest = hashlib.sha256(data).hexdigest()
        declared = candidate.get("core-metadata", candidate.get("dist-info-metadata"))
        if isinstance(declared, dict) and declared.get("sha256") != metadata_digest:
            raise ValueError(tr("backend.plugin_updates.official_package_metadata_verification_failed_check_for"))
        package = _package_metadata(data, distribution, latest)
        conflicts, dependencies = dependency_conflicts({**packages, distribution: package})
        if conflicts:
            details = message_list(conflicts[:8], "；")
            raise ValueError(
                tr("backend.plugin_updates.this_update_requires_additional_or_coordinated_dependency", p1=details)
            )
        dependencies = tuple(item for item in dependencies if not item.startswith(distribution + "=="))
        return PreparedUpdate(distribution, filename, url, digest, metadata_digest, package, dependencies)
    except (OSError, http.client.HTTPException) as exc:
        raise ValueError(tr("backend.plugin_updates.cannot_complete_the_official_update_compatibility_check")) from exc
    except (KeyError, TypeError, InvalidVersion, InvalidSpecifier, InvalidRequirement) as exc:
        raise ValueError(tr("backend.plugin_updates.official_package_metadata_cannot_be_safely_parsed")) from exc


def download_update(update: PreparedUpdate, directory: Path) -> Path:
    """Download only after confirmation; pin both wheel bytes and reviewed metadata."""
    try:
        data = _bounded_network(lambda: _read_artifact(update.url, limit=_MAX_WHEEL, timeout=30), _DOWNLOAD_TIMEOUT)
    except (OSError, http.client.HTTPException) as exc:
        raise ValueError(tr("backend.plugin_updates.cannot_download_the_update_check_the_network")) from exc
    if hashlib.sha256(data).hexdigest() != update.sha256:
        raise ValueError(tr("backend.plugin_updates.the_package_sha256_does_not_match_the"))
    wheel = directory / update.filename
    wheel.write_bytes(data)
    try:
        with zipfile.ZipFile(wheel) as archive:
            entries = [item for item in archive.infolist() if item.filename.endswith(".dist-info/METADATA")]
            if len(entries) != 1 or entries[0].file_size > _MAX_METADATA:
                raise ValueError(tr("backend.plugin_updates.the_package_metadata_is_invalid_no_update"))
            metadata = archive.read(entries[0])
    except (zipfile.BadZipFile, NotImplementedError) as exc:
        raise ValueError(tr("backend.plugin_updates.the_package_file_is_invalid_no_update")) from exc
    if hashlib.sha256(metadata).hexdigest() != update.metadata_sha256:
        raise ValueError(tr("backend.plugin_updates.downloaded_package_dependencies_do_not_match_the"))
    return wheel


def update_arguments(environment: Environment, wheel: Path, constraints: Path) -> list[str]:
    name, _, _, _ = parse_wheel_filename(wheel.name)
    if name not in COMPONENT_DISTRIBUTIONS.values():
        raise ValueError("unsupported component update")
    if environment.tool == "pip":
        args = [
            environment.executable,
            "-m",
            "pip",
            "--isolated",
            "install",
            "--disable-pip-version-check",
            "--no-input",
        ]
        args += ["--constraint", str(constraints)]
    elif environment.tool == "uv" and environment.tool_executable:
        args = [environment.tool_executable, "--no-config", "pip", "install", "--python", environment.executable]
        args += ["--no-python-downloads", "--offline", "--constraints", str(constraints)]
    else:
        raise RuntimeError(tr("backend.plugin_updates.no_installation_tool_is_available"))
    return [*args, "--no-deps", "--no-index", "--only-binary=:all:", str(wheel)]
