"""Review one compatible optional-component wheel without changing dependencies."""

from __future__ import annotations

import hashlib
import http.client
import re
import sys
import threading
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import compat32
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlsplit

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.tags import sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import InvalidVersion, Version
from sqlseed._utils.daemon_task import DaemonTask

from sqlseed_web import settings_updates
from sqlseed_web.plugin_environment import COMPONENT_DISTRIBUTIONS, Environment, InstalledPackage
from sqlseed_web.settings_environment import AI_INSTALL_REQUIREMENT

_MAX_METADATA = 1024 * 1024
_MAX_WHEEL = 64 * 1024 * 1024
_PLAN_TIMEOUT = 11
_DOWNLOAD_TIMEOUT = 35
_NETWORK_SLOT = threading.BoundedSemaphore(1)
_T = TypeVar("_T")


def _bounded_network(operation: Callable[[], _T], timeout: float) -> _T:
    # A slow DNS/header read cannot outlive the control channel's wait budget.
    # Timed-out network work can only return bytes/metadata, never publish a
    # plan or write files. Its slot remains occupied until it actually exits.
    if not _NETWORK_SLOT.acquire(blocking=False):
        raise ValueError("上一次更新查询仍在结束，请稍后重试；未修改任何组件。")

    def run() -> _T:
        try:
            return operation()
        finally:
            _NETWORK_SLOT.release()

    try:
        task = DaemonTask(run, name="sqlseed-update-read")
    except RuntimeError:
        _NETWORK_SLOT.release()
        raise
    if not task.wait(timeout):
        raise ValueError("更新查询或下载超时，请稍后重试；未修改任何组件。")
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
    if (
        parsed.scheme != "https"
        or parsed.netloc != "files.pythonhosted.org"
        or not parsed.path.startswith("/packages/")
        or parsed.query
        or parsed.fragment
        or any(character.isspace() for character in url)
    ):
        raise ValueError("软件包下载地址不属于受支持的官方源。")
    return parsed.path


def _read_artifact(url: str, *, limit: int, timeout: float) -> bytes:
    path = _artifact_path(url)
    connection = http.client.HTTPSConnection("files.pythonhosted.org", timeout=timeout)
    deadline = time.monotonic() + timeout
    try:
        connection.request("GET", path, headers={"User-Agent": "sqlseed-component-update"})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("官方软件包暂不可用，请稍后重试。")
        content = bytearray()
        while len(content) <= limit:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Package read timed out")
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            chunk = response.read1(min(65536, limit + 1 - len(content)))
            if not chunk:
                return bytes(content)
            content.extend(chunk)
        raise ValueError("软件包文件超过当前界面更新的大小限制。")
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
        raise ValueError("软件包元数据与所选更新不一致。")
    python_requirement = message.get("Requires-Python")
    if python_requirement and not SpecifierSet(str(python_requirement)).contains(
        ".".join(map(str, sys.version_info[:3]))
    ):
        raise ValueError("最新稳定版不支持当前 Python；未修改任何组件。")
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
                issues.add(f"{name} 依赖 {target} 的指定来源，无法在界面确认其兼容性")
            elif installed is None:
                issues.add(f"{name} 需要 {target}{requirement.specifier}（当前未安装）")
            elif not requirement.specifier.contains(installed.version, prereleases=True):
                issues.add(f"{name} 需要 {target}{requirement.specifier}（当前 {installed.version}）")
            else:
                dependencies.add(f"{target}=={installed.version}")
                pending.extend((target, requested) for requested in requirement.extras)
    return sorted(issues), tuple(sorted(dependencies))


def prepare_update(distribution: str, packages: dict[str, InstalledPackage]) -> PreparedUpdate:
    if distribution not in COMPONENT_DISTRIBUTIONS.values() or distribution not in packages:
        raise ValueError("只支持更新已安装的可选组件。")
    return _bounded_network(lambda: _prepare_update(distribution, dict(packages)), _PLAN_TIMEOUT)


def _prepare_update(distribution: str, packages: dict[str, InstalledPackage]) -> PreparedUpdate:
    try:
        payload = settings_updates._fetch_index(distribution)
        latest = settings_updates._latest_stable(distribution, payload)
        if Version(latest) <= Version(packages[distribution].version):
            raise ValueError("当前版本已不低于官方最新稳定版；不会降级开发版或本地版本。")
        if distribution == "sqlseed-ai" and not Requirement(AI_INSTALL_REQUIREMENT).specifier.contains(latest):
            raise ValueError("最新稳定版尚不满足当前 Web 的 AI 接口要求。")
        if not isinstance(payload, dict):
            raise TypeError("官方索引格式无效。")
        candidates: list[tuple[int, dict[str, Any]]] = []
        tags = {tag: index for index, tag in enumerate(sys_tags())}
        for file in payload["files"]:
            if not isinstance(file, dict) or file.get("yanked", False) is not False:
                continue
            filename = file.get("filename", "")
            if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", filename):
                continue
            try:
                name, version, _, wheel_tags = parse_wheel_filename(filename)
            except ValueError:
                continue
            if name != distribution or version != Version(latest) or not wheel_tags.intersection(tags):
                continue
            required_python = file.get("requires-python")
            if required_python and not SpecifierSet(required_python).contains(".".join(map(str, sys.version_info[:3]))):
                continue
            if not file.get("core-metadata", file.get("dist-info-metadata")):
                continue
            candidates.append((min(tags[tag] for tag in wheel_tags if tag in tags), file))
        if not candidates:
            raise ValueError("最新稳定版没有适用于当前 Python/平台且可预检元数据的 wheel；未修改任何组件。")
        candidate = min(candidates, key=lambda item: (item[0], item[1]["filename"]))[1]
        url, filename = str(candidate["url"]), str(candidate["filename"])
        _artifact_path(url)
        digest = candidate.get("hashes", {}).get("sha256", "")
        if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("官方软件包缺少有效的 SHA256 校验。")
        data = _read_artifact(url + ".metadata", limit=_MAX_METADATA, timeout=5)
        metadata_digest = hashlib.sha256(data).hexdigest()
        declared = candidate.get("core-metadata", candidate.get("dist-info-metadata"))
        if isinstance(declared, dict) and declared.get("sha256") != metadata_digest:
            raise ValueError("官方软件包元数据校验失败，请重新检查更新。")
        package = _package_metadata(data, distribution, latest)
        conflicts, dependencies = dependency_conflicts({**packages, distribution: package})
        if conflicts:
            details = "；".join(conflicts[:8])
            raise ValueError(
                f"此更新需要额外安装或联动调整依赖，已阻止执行：{details}。请使用原环境管理工具成组更新；界面不会隐式修改其他包。"
            )
        dependencies = tuple(item for item in dependencies if not item.startswith(distribution + "=="))
        return PreparedUpdate(distribution, filename, url, digest, metadata_digest, package, dependencies)
    except (OSError, http.client.HTTPException) as exc:
        raise ValueError("无法完成官方更新兼容性检查，请检查网络后重试；未修改任何组件。") from exc
    except (KeyError, TypeError, InvalidVersion, InvalidSpecifier, InvalidRequirement) as exc:
        raise ValueError("官方软件包元数据无法安全解析；未修改任何组件。") from exc


def download_update(update: PreparedUpdate, directory: Path) -> Path:
    """Download only after confirmation; pin both wheel bytes and reviewed metadata."""
    try:
        data = _bounded_network(lambda: _read_artifact(update.url, limit=_MAX_WHEEL, timeout=30), _DOWNLOAD_TIMEOUT)
    except (OSError, http.client.HTTPException) as exc:
        raise ValueError("无法完成更新包下载，请检查网络后重试；未执行更新。") from exc
    if hashlib.sha256(data).hexdigest() != update.sha256:
        raise ValueError("软件包 SHA256 与确认计划不一致；未执行更新。")
    wheel = directory / update.filename
    wheel.write_bytes(data)
    try:
        with zipfile.ZipFile(wheel) as archive:
            entries = [item for item in archive.infolist() if item.filename.endswith(".dist-info/METADATA")]
            if len(entries) != 1 or entries[0].file_size > _MAX_METADATA:
                raise ValueError("软件包元数据无效；未执行更新。")
            metadata = archive.read(entries[0])
    except (zipfile.BadZipFile, NotImplementedError) as exc:
        raise ValueError("软件包文件无效；未执行更新。") from exc
    if hashlib.sha256(metadata).hexdigest() != update.metadata_sha256:
        raise ValueError("下载的软件包依赖与确认计划不一致；未执行更新。")
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
        raise RuntimeError("没有可用的安装工具。")
    return [*args, "--no-deps", "--no-index", "--only-binary=:all:", str(wheel)]
