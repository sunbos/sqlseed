"""Exercise maintenance admission without changing the serving Python environment."""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
import threading
import time
import venv
import zipfile
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from packaging.requirements import Requirement

from sqlseed_web.app import create_app


@pytest.mark.parametrize("tool", ["pip", "uv"])
def test_ai_install_rejects_legacy_release_but_uninstall_uses_distribution_name(tmp_path: Path, tool: str) -> None:
    module = importlib.import_module("sqlseed_web.plugin_environment")
    environment = module.Environment(tmp_path, sys.executable, tool, "/test/uv" if tool == "uv" else None, None)
    constraints = tmp_path / "constraints.txt"
    arguments = module.installer_arguments(environment, "install", "sqlseed-ai", constraints)
    requirement = Requirement(arguments[-1])
    assert requirement.name == "sqlseed-ai"
    assert not requirement.specifier.contains("0.2.3")
    assert requirement.specifier.contains("0.2.4.dev244")
    assert requirement.specifier.contains("0.2.4")
    removal = module.installer_arguments(environment, "uninstall", "sqlseed-ai", constraints)
    assert removal[-1] == "sqlseed-ai"


def test_management_is_opt_in_and_normal_business_routes_remain_available() -> None:
    with TestClient(create_app(), base_url="http://127.0.0.1:8630", client=("127.0.0.1", 40000)) as client:
        response = client.get("/api/settings/plugins/management")
        assert response.status_code == 200
        assert response.json()["enabled"] is False
        assert response.json()["available"] is False
        assert response.json()["token"] is None
        assert "--manage-plugins" in response.json()["maintenance_command"]
        assert client.get("/api/connections").status_code == 200


def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    module = importlib.import_module("sqlseed_web.plugin_environment")
    (tmp_path / "pyvenv.cfg").write_text("include-system-site-packages = false\n", encoding="utf-8")
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path.parent))
    return module


@pytest.fixture(name="maintenance")
def fixture_maintenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    env = importlib.import_module("sqlseed_web.plugin_environment")
    manager = importlib.import_module("sqlseed_web.plugin_management")
    prefix = tmp_path / "venv"
    site = prefix / "site-packages"
    site.mkdir(parents=True)
    (prefix / "pyvenv.cfg").write_text("include-system-site-packages = false\n")
    distributions = {
        "sqlseed": ("1.2.3", ["Faker>=30"]),
        "sqlseed-web": ("0.1.0", ["sqlseed", "sqlseed-ai; extra == 'ai'"]),
        "Faker": ("30.0.0", []),
    }

    def install(name: str, version: str = "1.0.0", requires: list[str] | None = None) -> Path:
        directory = site / f"{name.replace('-', '_')}-{version}.dist-info"
        directory.mkdir()
        content = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        content += "".join(f"Requires-Dist: {requirement}\n" for requirement in requires or [])
        (directory / "METADATA").write_text(content)
        return directory

    for name, (version, requires) in distributions.items():
        install(name, version, requires)
    monkeypatch.setattr(env, "_distribution_paths", lambda: [str(site)])
    monkeypatch.setattr(env, "_environment", lambda: env.Environment(prefix, sys.executable, "pip", None, None))
    started, release = threading.Event(), threading.Event()
    invocations: list[Any] = []

    def run(arguments: list[str], output: Any, **kwargs: Any) -> Any:
        invocations.append(arguments)
        started.set()
        assert release.wait(5)
        install("mimesis")
        output("完成安装")
        return 0

    monkeypatch.setattr(manager, "run_installer", run)
    app = create_app(manage_plugins=True)
    with TestClient(app, base_url="http://127.0.0.1:8630", client=("127.0.0.1", 40000)) as client:
        status = client.get("/api/settings/plugins/management").json()
        headers = {"Origin": "http://127.0.0.1:8630", "X-Sqlseed-Management-Token": status["token"]}
        yield client, headers, install, started, release, invocations, prefix
        release.set()


@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/connections", "get"),
        ("/api/workbench/ai/config", "get"),
        ("/api/config/parse", "post"),
        ("/api/fs/browse", "get"),
        ("/api/workbench/runs", "get"),
    ],
)
def test_maintenance_rejects_all_business_apis(maintenance: Any, path: str, method: str) -> None:
    client = maintenance[0]
    response = getattr(client, method)(path)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "plugin_maintenance"
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Origin": "http://127.0.0.1:8631"},
        {"Origin": "http://127.0.0.1:8630", "X-Sqlseed-Management-Token": "wrong"},
    ],
)
def test_plan_requires_same_origin_and_session_token(maintenance: Any, headers: dict[str, str]) -> None:
    client = maintenance[0]
    response = client.post(
        "/api/settings/plugins/plan", json={"component_id": "mimesis", "action": "install"}, headers=headers
    )
    assert response.status_code == 403


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1.evil.example", "0.0.0.0", "localhost.evil.example"])
def test_management_rejects_dns_rebinding_hosts(maintenance: Any, host: str) -> None:
    client = maintenance[0]
    response = client.get("/api/settings/plugins/management", headers={"Host": host})
    assert response.status_code == 403
    assert "token" not in response.json()


def test_management_rejects_remote_clients() -> None:
    with TestClient(create_app(), base_url="http://localhost:8630", client=("192.0.2.5", 50000)) as client:
        assert client.get("/api/settings/plugins/management").status_code == 403


@pytest.mark.parametrize("component", ["core", "web", "base", "faker", "pip", "mimesis --upgrade", "../evil"])
def test_plan_only_accepts_optional_component_identifiers(maintenance: Any, component: str) -> None:
    client, headers = maintenance[:2]
    response = client.post(
        "/api/settings/plugins/plan", headers=headers, json={"component_id": component, "action": "uninstall"}
    )
    assert response.status_code == 422


def test_reverse_dependencies_block_cli_but_ignore_inactive_extras(maintenance: Any) -> None:
    client, headers, install = maintenance[:3]
    install("sqlseed-cli")
    install("sqlseed-ai", requires=["sqlseed-cli>=1.0", "mimesis; python_version < '2'"])
    response = client.post(
        "/api/settings/plugins/plan", headers=headers, json={"component_id": "cli", "action": "uninstall"}
    )
    assert response.status_code == 409
    assert "sqlseed-ai" in response.json()["detail"]["message"]
    ai = client.post("/api/settings/plugins/plan", headers=headers, json={"component_id": "ai", "action": "uninstall"})
    assert ai.status_code == 200
    assert ai.json()["distribution"] == "sqlseed-ai"
    assert "依赖" in " ".join(ai.json()["warnings"])


def test_execute_single_plan_freezes_existing_versions_and_requires_restart(maintenance: Any) -> None:
    client, headers, _, started, release, invocations, _ = maintenance
    plan = client.post(
        "/api/settings/plugins/plan", headers=headers, json={"component_id": "mimesis", "action": "install"}
    ).json()
    task = client.post("/api/settings/plugins/execute", headers=headers, json={"plan_id": plan["plan_id"]})
    assert task.status_code == 202
    assert started.wait(2)
    assert (
        client.post("/api/settings/plugins/execute", headers=headers, json={"plan_id": plan["plan_id"]}).status_code
        == 409
    )
    arguments = invocations[0]
    assert arguments[:4] == [sys.executable, "-m", "pip", "--isolated"]
    assert arguments[-1] == "mimesis"
    constraint_file = Path(arguments[arguments.index("--constraint") + 1])
    constraints = constraint_file.read_text(encoding="utf-8")
    assert "sqlseed==1.2.3" in constraints and "sqlseed-web==0.1.0" in constraints
    release.set()
    task_id = task.json()["task_id"]
    for _ in range(100):
        result = client.get(f"/api/settings/plugins/tasks/{task_id}").json()
        if result["status"] != "running":
            break
        threading.Event().wait(0.01)
    assert result["status"] == "succeeded"
    assert result["restart_required"] is True
    assert result["returncode"] == 0
    assert client.get("/api/settings/plugins/management").json()["available"] is False
    assert not constraint_file.exists()


def test_plan_revalidation_rejects_changed_metadata(maintenance: Any) -> None:
    client, headers, install = maintenance[:3]
    plan = client.post(
        "/api/settings/plugins/plan", headers=headers, json={"component_id": "mimesis", "action": "install"}
    ).json()
    install("unrelated-distribution")
    response = client.post("/api/settings/plugins/execute", headers=headers, json={"plan_id": plan["plan_id"]})
    assert response.status_code == 409
    assert not maintenance[5]


def test_maintenance_environment_snapshot_never_imports_plugins(
    maintenance: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = maintenance[0]
    original = importlib.import_module

    def guarded(name: str, package: str | None = None) -> Any:
        assert not name.startswith(("sqlseed_ai", "sqlseed_cli", "mcp_server_sqlseed", "mimesis"))
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", guarded)
    response = client.get("/api/settings/environment")
    assert response.status_code == 200
    assert response.json()["inspection"] == "metadata_only"


def test_environment_lock_excludes_other_processes(tmp_path: Path) -> None:
    module = importlib.import_module("sqlseed_web.plugin_environment")
    lock = module.EnvironmentLock(tmp_path, exclusive=False)
    lock.acquire()
    code = """from pathlib import Path
from sqlseed_web.plugin_environment import EnvironmentLock
import sys
try:
    EnvironmentLock(Path(sys.argv[1]), exclusive=True).acquire()
except RuntimeError:
    sys.exit(23)
sys.exit(0)
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path)], capture_output=True, check=False, timeout=10
        )
        assert result.returncode == 23, result.stderr.decode()
    finally:
        lock.release()
    assert (
        subprocess.run(
            [sys.executable, "-c", code, str(tmp_path)], capture_output=True, check=False, timeout=10
        ).returncode
        == 0
    )


@pytest.mark.parametrize("fault", ["system", "external", "shared"])
def test_environment_rejects_unsafe_install_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    module = importlib.import_module("sqlseed_web.plugin_environment")
    prefix = tmp_path / "env"
    prefix.mkdir()
    (prefix / "pyvenv.cfg").write_text(f"include-system-site-packages = {'true' if fault == 'shared' else 'false'}\n")
    if fault == "external":
        (prefix / "EXTERNALLY-MANAGED").write_text("managed")
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(sys, "base_prefix", str(prefix) if fault == "system" else str(tmp_path))
    environment = module._environment()
    assert environment.reason


def test_installer_output_is_bounded_redacted_and_timeout_is_real(tmp_path: Path) -> None:
    module = importlib.import_module("sqlseed_web.plugin_process")
    output: list[str] = []
    code = (
        "import time; print('https://user:secret@example.test/path?token=private', "
        "flush=True); print('x'*100000, flush=True); time.sleep(10)"
    )
    result = module.run_installer([sys.executable, "-c", code], output.append, timeout=0.15)
    assert result == -1
    text = json.dumps(output, ensure_ascii=False)
    assert len(text) < 35000
    assert "secret" not in text and "private" not in text
    assert "超时" in text


def test_long_output_line_is_discarded_until_newline() -> None:
    module = importlib.import_module("sqlseed_web.plugin_process")
    output: list[str] = []
    code = "print('https://example.test/' + 'x'*16000 + 'hidden-tail-secret'); print('ordinary next line')"
    assert module.run_installer([sys.executable, "-c", code], output.append, timeout=2) == 0
    assert "hidden-tail-secret" not in " ".join(output)
    assert "ordinary next line" in output


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process group semantics")
def test_parent_exit_cannot_leave_a_child_holding_the_output_pipe() -> None:
    module = importlib.import_module("sqlseed_web.plugin_process")
    output: list[str] = []
    code = "import subprocess, sys; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])"
    start = time.monotonic()
    assert module.run_installer([sys.executable, "-c", code], output.append, timeout=0.2) == -1
    assert time.monotonic() - start < 3


def test_metadata_outside_environment_is_not_a_managed_distribution(
    maintenance: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = importlib.import_module("sqlseed_web.plugin_environment")
    external = tmp_path / "outside"
    directory = external / "outside-1.dist-info"
    directory.mkdir(parents=True)
    (directory / "METADATA").write_text("Metadata-Version: 2.1\nName: outside\nVersion: 1\n")
    monkeypatch.setattr(module, "_distribution_paths", lambda: [str(external)])
    result = maintenance[0].get("/api/settings/plugins/management").json()
    assert result["available"] is False


def test_readonly_environment_still_starts_normal_web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("sqlseed_web.plugin_environment")
    (tmp_path / "pyvenv.cfg").write_text("include-system-site-packages = false\n")
    monkeypatch.setattr(
        module,
        "_environment",
        lambda: module.Environment(tmp_path, sys.executable, None, None, "当前 Python 环境不可写。"),
    )
    with TestClient(create_app()) as client:
        assert client.get("/api/health").status_code == 200
    assert not (tmp_path / ".sqlseed-web-environment.lock").exists()


def test_expired_plan_and_extra_request_fields_cannot_execute(
    maintenance: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, headers = maintenance[:2]
    plan = client.post(
        "/api/settings/plugins/plan", headers=headers, json={"component_id": "mimesis", "action": "install"}
    ).json()
    assert (
        client.post(
            "/api/settings/plugins/execute",
            headers=headers,
            json={"plan_id": plan["plan_id"], "command": "echo forbidden"},
        ).status_code
        == 422
    )
    module = importlib.import_module("sqlseed_web.plugin_management")
    old_clock = module.time.monotonic
    monkeypatch.setattr(module.time, "monotonic", lambda: old_clock() + 301)
    assert (
        client.post("/api/settings/plugins/execute", headers=headers, json={"plan_id": plan["plan_id"]}).status_code
        == 409
    )
    assert not maintenance[5]


def test_nonzero_installer_result_is_failure_and_requires_restart(
    maintenance: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, headers = maintenance[:2]
    module = importlib.import_module("sqlseed_web.plugin_management")
    monkeypatch.setattr(module, "run_installer", lambda *args, **kwargs: 17)
    plan = client.post(
        "/api/settings/plugins/plan", headers=headers, json={"component_id": "mimesis", "action": "install"}
    ).json()
    task = client.post("/api/settings/plugins/execute", headers=headers, json={"plan_id": plan["plan_id"]}).json()
    for _ in range(100):
        result = client.get(f"/api/settings/plugins/tasks/{task['task_id']}").json()
        if result["status"] != "running":
            break
        threading.Event().wait(0.01)
    assert result["status"] == "failed" and result["returncode"] == 17
    assert result["restart_required"] is True
    assert client.get("/api/settings/plugins/management").json()["available"] is False


@pytest.mark.parametrize("tool", ["pip", "uv"])
def test_real_installer_installs_and_uninstalls_only_in_a_temporary_venv(tmp_path: Path, tool: str) -> None:
    uv = shutil.which("uv")
    if tool == "uv" and uv is None:
        pytest.skip("uv is needed for the isolated installer integration")
    environment_module = importlib.import_module("sqlseed_web.plugin_environment")
    process_module = importlib.import_module("sqlseed_web.plugin_process")
    before = sorted((package.metadata["Name"], package.version) for package in metadata.distributions())
    prefix = tmp_path / "isolated"
    venv.EnvBuilder(with_pip=tool == "pip", symlinks=sys.platform != "win32").create(prefix)
    target = prefix / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    installed_code = (
        "from importlib.metadata import distributions; print(sorted(d.metadata['Name'] for d in distributions()))"
    )
    target_before = subprocess.run(
        [str(target), "-c", installed_code], capture_output=True, text=True, check=True, timeout=5
    ).stdout
    directory = tmp_path / "wheels"
    directory.mkdir()
    wheel = directory / "mimesis-0.0.1-py3-none-any.whl"
    files = {
        "mimesis/__init__.py": "__version__ = '0.0.1'\n",
        "mimesis-0.0.1.dist-info/METADATA": "Metadata-Version: 2.1\nName: mimesis\nVersion: 0.0.1\n",
        "mimesis-0.0.1.dist-info/WHEEL": "Wheel-Version: 1.0\nGenerator: sqlseed-test\nRoot-Is-Purelib: true\nTag: "
        "py3-none-any\n",
    }
    files["mimesis-0.0.1.dist-info/RECORD"] = (
        "".join(f"{name},,\n" for name in files) + "mimesis-0.0.1.dist-info/RECORD,,\n"
    )
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    environment = environment_module.Environment(prefix, str(target), tool, uv, None)
    constraints = tmp_path / "constraints.txt"
    constraints.write_text("")
    arguments = environment_module.installer_arguments(environment, "install", "mimesis", constraints)
    arguments[-1:-1] = [*(["--offline"] if tool == "uv" else []), "--no-index", "--find-links", str(directory)]
    output: list[str] = []
    assert process_module.run_installer(arguments, output.append, timeout=10) == 0, "\n".join(output)
    probe = subprocess.run(
        [str(target), "-c", "from importlib.metadata import version; print(version('mimesis'))"],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    assert probe.stdout.strip() == "0.0.1"
    removal = environment_module.installer_arguments(environment, "uninstall", "mimesis", constraints)
    assert process_module.run_installer(removal, output.append, timeout=10) == 0, "\n".join(output)
    probe = subprocess.run([str(target), "-c", installed_code], capture_output=True, text=True, check=True, timeout=5)
    assert probe.stdout == target_before
    assert before == sorted((package.metadata["Name"], package.version) for package in metadata.distributions())


def test_environment_rejects_install_directories_outside_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _isolated_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(module.sysconfig, "get_path", lambda name: str(tmp_path.parent))
    assert module._environment().reason


def test_missing_core_metadata_does_not_allow_plugin_installation(maintenance: Any) -> None:
    client, headers, _, _, _, _, prefix = maintenance
    shutil.rmtree(prefix / "site-packages" / "sqlseed-1.2.3.dist-info")
    status = client.get("/api/settings/plugins/management").json()
    assert status["available"] is False
    assert (
        client.post(
            "/api/settings/plugins/plan", headers=headers, json={"component_id": "mimesis", "action": "install"}
        ).status_code
        == 409
    )


def test_windows_maintenance_is_explicitly_unsupported_without_affecting_manual_guidance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _isolated_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(module.sysconfig, "get_path", lambda name: str(tmp_path))
    assert "Windows" in module._environment().reason
