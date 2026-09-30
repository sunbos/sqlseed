"""Optional-component updates are reviewed, dependency-frozen and interpreter-bound."""

from __future__ import annotations

import hashlib
import http.client
import io
import shutil
import subprocess
import sys
import threading
import venv
import zipfile
from dataclasses import replace
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from sqlseed_web import plugin_environment as environment
from sqlseed_web import plugin_updates as updates
from sqlseed_web.app import create_app
from sqlseed_web.plugin_management import ExecuteRequest, PlanRequest
from sqlseed_web.plugin_process import run_installer
from sqlseed_web.supervised_plugins import SupervisedPluginManager

from .component_test_support import HTTPExchange, RecordingController, acquired_with_timeout


def package(version: str, *requirements: str) -> environment.InstalledPackage:
    return environment.InstalledPackage(version, tuple(sorted(requirements)))


def wheel(name: str, version: str, *requirements: str) -> tuple[str, bytes, bytes]:
    stem = f"{name.replace('-', '_')}-{version}"
    description = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\nRequires-Python: >=3.10\n"
    description += "".join(f"Requires-Dist: {requirement}\n" for requirement in requirements)
    payload = {
        f"{name.replace('-', '_')}/__init__.py": f"__version__ = '{version}'\n",
        f"{stem}.dist-info/METADATA": description,
        f"{stem}.dist-info/WHEEL": "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    payload[f"{stem}.dist-info/RECORD"] = "".join(f"{path},,\n" for path in payload) + f"{stem}.dist-info/RECORD,,\n"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for path, content in payload.items():
            archive.writestr(path, content)
    return f"{stem}-py3-none-any.whl", output.getvalue(), description.encode()


def official_wheel(
    monkeypatch: pytest.MonkeyPatch, *requirements: str, version: str = "2.0"
) -> tuple[bytes, list[str]]:
    filename, data, description = wheel("mimesis", version, *requirements)
    url = f"https://files.pythonhosted.org/packages/test/{filename}"
    calls: list[str] = []
    index = {
        "files": [
            {
                "filename": filename,
                "url": url,
                "yanked": False,
                "hashes": {"sha256": hashlib.sha256(data).hexdigest()},
                "core-metadata": {"sha256": hashlib.sha256(description).hexdigest()},
                "requires-python": ">=3.10",
            }
        ]
    }
    monkeypatch.setattr(updates.settings_updates, "_fetch_index", lambda _: index)

    def read(address: str, **kwargs: Any) -> bytes:
        calls.append(address)
        assert address in {url, url + ".metadata"}
        return description if address.endswith(".metadata") else data

    monkeypatch.setattr(updates, "_read_artifact", read)
    return data, calls


def test_plan_checks_target_and_reverse_dependencies_and_downloads_only_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, calls = official_wheel(monkeypatch, "shared>=1", "optional; extra == 'feature'")
    packages = {"mimesis": package("1.0"), "shared": package("1.5"), "consumer": package("1", "mimesis<3")}
    result = updates.prepare_update("mimesis", packages)
    assert result.package == package("2.0", "shared>=1", "optional; extra == 'feature'")
    assert result.dependencies == ("shared==1.5",)
    assert len(calls) == 1
    assert calls[0].endswith(".metadata")
    assert packages["mimesis"].version == "1.0"


@pytest.mark.parametrize(
    "requirements,extra_packages,expected",
    [
        (("missing>=1",), {}, "未安装"),
        (("shared>=2",), {"shared": package("1")}, "当前 1"),
        ((), {"consumer": package("1", "mimesis<2")}, "consumer 需要 mimesis<2"),
        (("shared[extra]",), {"shared": package("1", "missing; extra == 'extra'")}, "shared 需要 missing"),
        (("optional; extra == 'feature'",), {"consumer": package("1", "mimesis[feature]")}, "optional"),
        (("shared @ https://example.test/private.whl",), {"shared": package("1.0")}, "指定来源"),
    ],
)
def test_dependency_changes_are_blocked_before_download_or_install(
    monkeypatch: pytest.MonkeyPatch, requirements: tuple[str, ...], extra_packages: dict[str, Any], expected: str
) -> None:
    _, calls = official_wheel(monkeypatch, *requirements)
    packages = {"mimesis": package("1.0"), **extra_packages}
    with pytest.raises(ValueError, match=expected):
        updates.prepare_update("mimesis", packages)
    assert len(calls) == 1
    assert calls[0].endswith(".metadata")


@pytest.mark.parametrize("current", ["2.0", "2.1.dev1", "2.0+local", "3.0"])
def test_latest_stable_cannot_downgrade_current_or_development_versions(
    monkeypatch: pytest.MonkeyPatch, current: str
) -> None:
    _, calls = official_wheel(monkeypatch)
    packages = {"mimesis": package(current)}
    with pytest.raises(ValueError, match="不会降级"):
        updates.prepare_update("mimesis", packages)
    assert not calls


def test_missing_target_and_protected_distributions_are_rejected() -> None:
    for target in ("sqlseed", "sqlseed-web", "faker", "arbitrary", "mimesis"):
        packages = {"sqlseed": package("1.0")}
        with pytest.raises(ValueError, match="可选组件"):
            updates.prepare_update(target, packages)


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"requires-python": ">=99"}, "当前 Python/平台"),
        ({"core-metadata": False}, "可预检元数据"),
        ({"hashes": {"sha256": "missing"}}, "缺少有效的 SHA256"),
        ({"core-metadata": {"sha256": "0" * 64}}, "元数据校验失败"),
    ],
)
def test_unsupported_or_unverified_release_never_becomes_an_update_plan(
    monkeypatch: pytest.MonkeyPatch, change: dict[str, Any], expected: str
) -> None:
    _, calls = official_wheel(monkeypatch)
    payload = updates.settings_updates._fetch_index("mimesis")
    payload["files"][0].update(change)
    packages = {"mimesis": package("1.0")}
    with pytest.raises(ValueError, match=expected):
        updates.prepare_update("mimesis", packages)
    assert all(address.endswith(".metadata") for address in calls)


@pytest.mark.parametrize(
    "url",
    [
        "http://files.pythonhosted.org/packages/a.whl",
        "https://example.test/packages/a.whl",
        "https://files.pythonhosted.org@evil.test/packages/a.whl",
        "https://files.pythonhosted.org/packages/a.whl?token=x",
        "file:///packages/a.whl",
        "https://files.pythonhosted.org:443/packages/a.whl",
    ],
)
def test_artifact_host_cannot_be_overridden(url: str) -> None:
    with pytest.raises(ValueError, match="官方源"):
        updates._artifact_path(url)


def test_download_checks_both_published_wheel_hash_and_reviewed_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, calls = official_wheel(monkeypatch)
    planned = updates.prepare_update("mimesis", {"mimesis": package("1.0")})
    invalid_wheel_hash = replace(planned, sha256="0" * 64)
    with pytest.raises(ValueError, match="SHA256"):
        updates.download_update(invalid_wheel_hash, tmp_path)
    assert not list(tmp_path.iterdir())
    invalid_metadata_hash = replace(planned, metadata_sha256="0" * 64)
    with pytest.raises(ValueError, match="依赖与确认计划不一致"):
        updates.download_update(invalid_metadata_hash, tmp_path)
    path = updates.download_update(planned, tmp_path)
    assert path.name == planned.filename
    assert hashlib.sha256(path.read_bytes()).hexdigest() == planned.sha256
    assert len(calls) == 4


def test_update_api_preserves_origin_token_and_component_allowlist() -> None:
    with TestClient(create_app(), base_url="http://127.0.0.1:8630", client=("127.0.0.1", 40000)) as client:
        assert (
            client.post("/api/settings/plugins/plan", json={"component_id": "mimesis", "action": "update"}).status_code
            == 403
        )
        headers = {
            "Origin": "http://127.0.0.1:8630",
            "X-Sqlseed-Management-Token": client.app.state.plugin_manager.token,
        }
        for target in ("core", "web", "faker", "other"):
            assert (
                client.post(
                    "/api/settings/plugins/plan", headers=headers, json={"component_id": target, "action": "update"}
                ).status_code
                == 422
            )
        assert (
            client.post(
                "/api/settings/plugins/plan",
                headers=headers,
                json={"component_id": "mimesis", "action": "update", "url": "https://evil.test"},
            ).status_code
            == 422
        )


@pytest.mark.parametrize(
    "status,body,timeout,expected",
    [
        (302, b"redirect", 5, "暂不可用"),
        (200, b"x" * 33, 5, "大小限制"),
        (200, b"small", 0, "timed out"),
    ],
)
def test_download_transport_rejects_redirect_oversize_and_expiry(
    monkeypatch: pytest.MonkeyPatch, status: int, body: bytes, timeout: float, expected: str
) -> None:
    exchange = HTTPExchange(status=status, body=body)
    monkeypatch.setattr(updates.http.client, "HTTPSConnection", exchange.connection)
    with pytest.raises((ValueError, TimeoutError), match=expected):
        updates._read_artifact("https://files.pythonhosted.org/packages/a.whl", limit=32, timeout=timeout)
    assert exchange.calls == [
        ("files.pythonhosted.org", timeout),
        ("GET", "/packages/a.whl", {"User-Agent": "sqlseed-component-update"}),
    ]
    assert exchange.closed == [True]


@pytest.fixture(name="update_manager")
def fixture_update_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    prefix = tmp_path / "environment"
    site = prefix / "site"
    site.mkdir(parents=True)
    (prefix / "pyvenv.cfg").write_text("include-system-site-packages = false\n")
    for name in ("sqlseed", "sqlseed-web", "faker", "shared", "mimesis"):
        path = site / f"{name}-1.0.dist-info"
        path.mkdir()
        (path / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")
    monkeypatch.setattr(
        environment, "_environment", lambda: environment.Environment(prefix, sys.executable, "pip", None, None)
    )
    monkeypatch.setattr(environment, "_distribution_paths", lambda: [str(site)])
    official_wheel(monkeypatch, "shared>=1")
    events: list[str] = []
    installs: list[Any] = []

    monkeypatch.setattr(
        "sqlseed_web.plugin_management.run_installer", lambda *args, **kwargs: installs.append(args) or 0
    )
    manager = SupervisedPluginManager(RecordingController(restored={}, calls=events))
    manager.start()
    yield manager, site, events, installs
    manager.stop()


def test_update_plan_metadata_snapshot_is_rechecked_before_maintenance(update_manager: Any) -> None:
    manager, site, events, installs = update_manager
    plan = manager.plan(PlanRequest(component_id="mimesis", action="update"))
    (site / "shared-1.0.dist-info/METADATA").write_text("Metadata-Version: 2.1\nName: shared\nVersion: 1.1\n")
    request = ExecuteRequest(plan_id=plan["plan_id"])
    with pytest.raises(HTTPException) as caught:
        manager.execute(request)
    assert caught.value.status_code == 409
    assert "环境已发生变化" in caught.value.detail["message"]
    assert not installs
    assert events == ["pause", "resume"]


def test_slow_plan_has_total_budget_and_late_result_cannot_publish_a_plan(
    update_manager: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, _, events, installs = update_manager
    started, release = threading.Event(), threading.Event()
    original = updates.settings_updates._fetch_index

    def slow(project: str) -> object:
        started.set()
        assert release.wait(5)
        return original(project)

    monkeypatch.setattr(updates.settings_updates, "_fetch_index", slow)
    monkeypatch.setattr(updates, "_PLAN_TIMEOUT", 0.01)
    try:
        request = PlanRequest(component_id="mimesis", action="update")
        with pytest.raises(HTTPException) as caught:
            manager.plan(request)
        assert started.is_set()
        assert "超时" in caught.value.detail["message"]
        assert manager._plan is None
        assert manager.status()["available"] is True
        retry_request = PlanRequest(component_id="mimesis", action="update")
        with pytest.raises(HTTPException) as next_request:
            manager.plan(retry_request)
        assert "上一次更新查询" in next_request.value.detail["message"]
        assert not events
        assert not installs
    finally:
        release.set()
        with acquired_with_timeout(updates._NETWORK_SLOT, timeout=5):
            pass
    assert manager._plan is None, "late read-only completion cannot publish a previously timed-out plan"


def test_timed_out_wheel_read_cannot_write_after_service_recovery(
    update_manager: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, _, events, installs = update_manager
    plan = manager.plan(PlanRequest(component_id="mimesis", action="update"))
    started, release = threading.Event(), threading.Event()
    original_read, original_download = updates._read_artifact, updates.download_update
    directories = []

    def slow(address: str, *, limit: int, timeout: float) -> bytes:
        started.set()
        assert release.wait(5)
        return original_read(address, limit=limit, timeout=timeout)

    def capture(update: Any, directory: Path) -> Path:
        directories.append(directory)
        return original_download(update, directory)

    monkeypatch.setattr(updates, "_read_artifact", slow)
    monkeypatch.setattr(updates, "download_update", capture)
    monkeypatch.setattr(updates, "_DOWNLOAD_TIMEOUT", 0.01)
    try:
        task = manager.execute(ExecuteRequest(plan_id=plan["plan_id"]))
        manager._worker.join(5)
        result = manager.task_snapshot(task["task_id"])
        assert started.is_set()
        assert result["status"] == "failed"
        assert result["service_ready"] is True
        assert any("超时" in line for line in result["output"])
        assert events == ["pause", "maintenance", "restore"]
        assert not installs
        assert len(directories) == 1
        assert not directories[0].exists()
    finally:
        release.set()
        with acquired_with_timeout(updates._NETWORK_SLOT, timeout=5):
            pass
    assert not directories[0].exists(), "late bytes must never recreate a cleaned-up download directory"


@pytest.mark.parametrize(
    "failure",
    [
        "metadata_changed",
        "environment_changed",
        "installer_changed",
        "permissions_changed",
        "http",
        "hash",
        "corrupt_wheel",
    ],
)
def test_update_download_failure_or_environment_race_never_invokes_installer_and_cleans_temp(
    update_manager: Any, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    manager, site, events, installs = update_manager
    plan = manager.plan(PlanRequest(component_id="mimesis", action="update"))
    original_read = updates._read_artifact
    directories = []
    original_download = updates.download_update

    def capture(update: Any, directory: Path) -> Path:
        directories.append(directory)
        return original_download(update, directory)

    def read(address: str, *, limit: int, timeout: float) -> bytes:
        if failure == "metadata_changed":
            (site / "shared-1.0.dist-info/METADATA").write_text("Metadata-Version: 2.1\nName: shared\nVersion: 1.1\n")
        if failure == "environment_changed":
            current = manager.environment
            monkeypatch.setattr(environment, "_environment", lambda: replace(current, executable="other-python"))
        if failure == "installer_changed":
            current = manager.environment
            monkeypatch.setattr(
                environment, "_environment", lambda: replace(current, tool="uv", tool_executable="/other/uv")
            )
        if failure == "permissions_changed":
            current = manager.environment
            monkeypatch.setattr(environment, "_environment", lambda: replace(current, reason="not writable"))
        if failure == "http":
            raise http.client.IncompleteRead(b"private")
        return (
            b"corrupted"
            if failure in {"hash", "corrupt_wheel"}
            else original_read(address, limit=limit, timeout=timeout)
        )

    if failure == "corrupt_wheel":
        manager._plan["_update"] = replace(manager._plan["_update"], sha256=hashlib.sha256(b"corrupted").hexdigest())
    monkeypatch.setattr(updates, "_read_artifact", read)
    monkeypatch.setattr(updates, "download_update", capture)
    task = manager.execute(ExecuteRequest(plan_id=plan["plan_id"]))
    manager._worker.join(5)
    result = manager.task_snapshot(task["task_id"])
    assert result["status"] == "failed"
    assert result["service_ready"] is True
    assert events == ["pause", "maintenance", "restore"]
    assert not installs
    assert len(directories) == 1
    assert not directories[0].exists()


@pytest.mark.parametrize("tool", ["pip", "uv"])
def test_real_confirmed_update_only_changes_selected_package_in_temporary_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str
) -> None:
    uv = shutil.which("uv")
    if tool == "uv" and uv is None:
        pytest.skip("uv is required for the isolated installer integration")
    host_before = sorted((item.metadata["Name"], item.version) for item in metadata.distributions())
    prefix = tmp_path / "venv"
    venv.EnvBuilder(with_pip=tool == "pip", symlinks=sys.platform != "win32").create(prefix)
    python = prefix / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    site = subprocess.run(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout.strip()
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    paths = []
    for name, requirements in (
        ("sqlseed", ("Faker>=1",)),
        ("sqlseed-web", ("sqlseed>=1",)),
        ("Faker", ()),
        ("mimesis", ("shared>=1",)),
        ("shared", ()),
    ):
        filename, content, _ = wheel(name, "1.0", *requirements)
        path = wheels / filename
        path.write_bytes(content)
        paths.append(str(path))
    args = (
        [str(python), "-m", "pip", "--isolated", "install"]
        if tool == "pip"
        else [str(uv), "--no-config", "pip", "install", "--python", str(python), "--offline"]
    )
    output: list[str] = []
    assert run_installer([*args, "--no-index", "--no-deps", *paths], output.append, timeout=40) == 0, output
    monkeypatch.setattr(
        environment, "_environment", lambda: environment.Environment(prefix, str(python), tool, uv, None)
    )
    monkeypatch.setattr(environment, "_distribution_paths", lambda: [site])
    before = environment.installed_packages(prefix)
    _, reads = official_wheel(monkeypatch, "shared>=1")

    controller = RecordingController(restored={"restored_connections": 0})
    manager = SupervisedPluginManager(controller)
    manager.start()
    try:
        plan = manager.plan(PlanRequest(component_id="mimesis", action="update"))
        assert plan["version"] == "1.0"
        assert plan["target_version"] == "2.0"
        assert "_update" not in plan
        assert "url" not in plan["artifact"]
        assert len(reads) == 1
        assert environment.installed_packages(prefix) == before
        assert not controller.calls
        task = manager.execute(ExecuteRequest(plan_id=plan["plan_id"]))
        assert manager._worker is not None
        manager._worker.join(45)
        result = manager.task_snapshot(task["task_id"])
        assert result["status"] == "succeeded", result
        assert result["service_ready"] is True
        assert controller.calls == ["pause", "maintenance", "restore"]
        after = environment.installed_packages(prefix)
        assert after["mimesis"] == package("2.0", "shared>=1")
        assert {name: item for name, item in after.items() if name != "mimesis"} == {
            name: item for name, item in before.items() if name != "mimesis"
        }
        repeated_request = ExecuteRequest(plan_id=plan["plan_id"])
        with pytest.raises(HTTPException):
            manager.execute(repeated_request)
    finally:
        manager.stop()
    assert host_before == sorted((item.metadata["Name"], item.version) for item in metadata.distributions())
