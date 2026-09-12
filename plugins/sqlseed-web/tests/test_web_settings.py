"""Persist ordinary AI settings while keeping credentials scoped to their service."""

from __future__ import annotations

import builtins
import importlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from tests.assertions import assert_empty
from tests.sqlite_helpers import sqlite_connection

from sqlseed_web import api, settings_environment, workbench_ai
from sqlseed_web.app import create_app
from sqlseed_web.state import UIState


def _record_model_requests(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    requests: list[str] = []

    def probe(url: str, **kwargs: Any) -> httpx.Response:
        requests.append(url)
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(httpx, "get", probe)
    return requests


@pytest.fixture(name="settings_client")
def fixture_settings_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, UIState, Path]]:
    # Tests replace the probe clock and subprocess boundary. A previous test's
    # cached result can otherwise match the same interpreter and 30-second slot.
    settings_environment._probe_version.cache_clear()
    for name in tuple(os.environ):
        if name.startswith("SQLSEED_AI_") or name in {"OPENAI_API_KEY", "GOOGLE_API_KEY", "OPENAI_BASE_URL"}:
            monkeypatch.delenv(name)
    path = tmp_path / "settings.json"
    monkeypatch.setenv("SQLSEED_WEB_SETTINGS_PATH", str(path))
    registry = UIState()
    monkeypatch.setattr(api, "state", registry)
    monkeypatch.setattr(workbench_ai, "state", registry)
    try:
        with TestClient(create_app()) as client:
            # App construction probes the real installer. Test clocks may
            # reuse that slot, so isolate the boundary after startup as well.
            settings_environment._probe_version.cache_clear()
            yield client, registry, path
    finally:
        settings_environment._probe_version.cache_clear()


def configured(**changes: Any) -> dict[str, Any]:
    return {"backend": "openai_compat", "model": "model-one", "base_url": "https://one.example.test/v1", **changes}


def test_settings_survive_restart_without_persisting_key(settings_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("sqlseed_ai")
    client, _, path = settings_client
    response = client.post("/api/workbench/ai/config", json=configured(api_key="private-session-token"))
    assert response.status_code == 200
    assert path.exists(), "Ordinary settings must survive a Web restart"
    saved = json.loads(path.read_text())
    assert saved == configured()
    assert "private-session-token" not in response.text + path.read_text()
    monkeypatch.setattr(workbench_ai, "state", UIState())
    restarted = client.get("/api/workbench/ai/config").json()
    assert restarted["effective"] == {**configured(), "api_key_present": False}
    assert restarted["sources"]["model"] == "saved"
    assert restarted["sources"]["api_key"] == "none"
    assert restarted["storage"]["api_key"] == "session_or_environment"
    assert restarted["ready"] is False


def test_same_service_keeps_key_but_new_host_and_backend_do_not(settings_client: Any) -> None:
    pytest.importorskip("sqlseed_ai")
    client, registry, _ = settings_client
    client.post("/api/workbench/ai/config", json=configured(api_key="private-token"))
    same = client.post("/api/workbench/ai/config", json=configured(model="model-two", api_key="")).json()
    assert same["effective"]["api_key_present"] is True
    moved = client.post("/api/workbench/ai/config", json=configured(base_url="https://two.example.test/v1")).json()
    assert moved["effective"]["api_key_present"] is False
    assert "private-token" not in registry.get_ai_override().values()
    client.post("/api/workbench/ai/config", json=configured(api_key="new-token"))
    moved_backend = client.post("/api/workbench/ai/config", json=configured(backend="ollama")).json()
    assert moved_backend["effective"]["api_key_present"] is False


def test_env_key_is_only_reused_at_its_own_endpoint(settings_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("sqlseed_ai")
    client, _, _ = settings_client
    monkeypatch.setenv("SQLSEED_AI_BASE_URL", configured()["base_url"])
    monkeypatch.setenv("SQLSEED_AI_API_KEY", "private-env-token")
    monkeypatch.setenv("SQLSEED_AI_MODEL", "env-model")
    initial = client.get("/api/workbench/ai/config").json()
    assert initial["effective"]["api_key_present"] is True
    assert initial["sources"]["api_key"] == "environment"
    same = client.post("/api/workbench/ai/config", json=configured()).json()
    assert same["effective"]["api_key_present"] is True
    changed = client.post("/api/workbench/ai/config", json=configured(base_url="https://two.example.test/v1")).json()
    assert changed["effective"]["api_key_present"] is False


def test_draft_probe_uses_draft_and_does_not_save(settings_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("sqlseed_ai")
    client, registry, path = settings_client
    client.post("/api/workbench/ai/config", json=configured(api_key="saved-secret"))
    before_disk, before_memory = path.read_bytes(), registry.get_ai_override()
    requests: list[tuple[str, dict[str, Any]]] = []

    def probe(url: str, **kwargs: Any) -> httpx.Response:
        requests.append((url, kwargs))
        return httpx.Response(200, json={"data": [{"id": "draft-model"}]})

    monkeypatch.setattr(httpx, "get", probe)
    draft = configured(base_url="https://draft.example.test/v1", api_key="draft-secret")
    result = client.post("/api/workbench/ai/test", json=draft)
    assert result.status_code == 200
    assert requests[0][0] == "https://draft.example.test/v1/models"
    assert requests[0][1]["headers"]["Authorization"] == "Bearer draft-secret"
    assert result.json()["models"] == ["draft-model"]
    assert datetime.fromisoformat(result.json()["checked_at"]).tzinfo is not None
    assert path.read_bytes() == before_disk and registry.get_ai_override() == before_memory
    assert "secret" not in result.text
    assert client.post("/api/workbench/ai/test").json()["ok"] is True
    assert requests[-1][0] == configured()["base_url"] + "/models"


@pytest.mark.parametrize("credential_source", ["session", "environment"])
def test_draft_probe_never_sends_old_key_to_new_host(
    settings_client: Any, monkeypatch: pytest.MonkeyPatch, credential_source: str
) -> None:
    pytest.importorskip("sqlseed_ai")
    client, _, _ = settings_client
    if credential_source == "environment":
        monkeypatch.setenv("SQLSEED_AI_API_KEY", "private-old-key")
        monkeypatch.setenv("SQLSEED_AI_BASE_URL", configured()["base_url"])
    else:
        client.post("/api/workbench/ai/config", json=configured(api_key="private-old-key"))
    requests = _record_model_requests(monkeypatch)
    response = client.post("/api/workbench/ai/test", json=configured(base_url="https://other.example.test/v1"))
    assert response.json()["ok"] is False
    assert_empty(requests, list)


def test_clear_key_blocks_environment_fallback_in_session(
    settings_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sqlseed_ai")
    client, _, path = settings_client
    monkeypatch.setenv("SQLSEED_AI_API_KEY", "private-env-key")
    monkeypatch.setenv("SQLSEED_AI_BASE_URL", configured()["base_url"])
    cleared = client.post("/api/workbench/ai/config", json=configured(clear_api_key=True)).json()
    assert cleared["effective"]["api_key_present"] is False
    assert client.get("/api/workbench/ai/config").json()["effective"]["api_key_present"] is False
    assert "api_key" not in path.read_text()


def test_failed_disk_write_does_not_change_effective_settings(settings_client: Any) -> None:
    pytest.importorskip("sqlseed_ai")
    client, registry, path = settings_client
    client.post("/api/workbench/ai/config", json=configured(api_key="old-secret"))
    before = registry.get_ai_override()
    path.unlink()
    path.mkdir()  # A real filesystem error, without mocking storage internals.
    result = client.post("/api/workbench/ai/config", json=configured(model="new-model", api_key="new-secret"))
    assert result.status_code == 503
    assert registry.get_ai_override() == before
    assert "secret" not in result.text
    assert client.get("/api/workbench/ai/config").json()["effective"]["model"] == "model-one"


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/private",
        "https://user:private@example.test/v1",
        "https://example.test:bad/v1",
        "https://example.test/v1?key=private",
    ],
)
def test_settings_and_probe_reject_unsafe_urls(settings_client: Any, url: str) -> None:
    client, _, _ = settings_client
    for endpoint in ("config", "test"):
        result = client.post(f"/api/workbench/ai/{endpoint}", json=configured(base_url=url))
        assert result.status_code == 422
        assert "private" not in result.text


def test_probe_failure_is_redacted(settings_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("sqlseed_ai")
    client, _, _ = settings_client

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("private-token from https://user:password@example.test")

    monkeypatch.setattr(httpx, "get", fail)
    result = client.post("/api/workbench/ai/test", json=configured(api_key="private-token"))
    assert result.json()["ok"] is False
    assert result.json()["models"] == []
    assert result.json()["checked_at"]
    assert "private-token" not in result.text and "password" not in result.text


def test_environment_uses_current_interpreter_and_distribution_metadata(settings_client: Any) -> None:
    client, _, _ = settings_client
    response = client.get("/api/settings/environment")
    assert response.status_code == 200
    result = response.json()
    assert result["python"]["version"] == platform.python_version()
    packages = {item["id"]: item for item in result["packages"]}
    assert set(packages) == {"core", "cli", "web", "ai", "mcp"}
    assert packages["web"]["version"] == metadata.version("sqlseed-web")
    assert packages["core"]["installed"] is True and packages["core"]["available"] is True
    assert {item["id"] for item in result["providers"]} == {"base", "faker", "mimesis"}
    assert result["python"]["implementation"] == platform.python_implementation()
    for item in result["packages"] + result["providers"]:
        if item["installed"]:
            assert item["version"] == metadata.version(item["distribution"])


def test_environment_explains_component_roles_and_real_dependencies(settings_client: Any) -> None:
    client, _, path = settings_client
    result = client.get("/api/settings/environment").json()
    items = {item["id"]: item for item in result["packages"] + result["providers"]}
    assert {identifier: (item["category"], item["requirement"]) for identifier, item in items.items()} == {
        "core": ("application", "required"),
        "web": ("application", "required"),
        "ai": ("extension", "optional"),
        "cli": ("extension", "optional"),
        "mcp": ("extension", "optional"),
        "base": ("provider", "builtin"),
        "faker": ("provider", "required"),
        "mimesis": ("provider", "optional"),
    }
    assert {identifier: item["dependency_ids"] for identifier, item in items.items()} == {
        "core": ["faker"],
        "web": ["core"],
        "ai": ["core", "cli"],
        "cli": ["core"],
        "mcp": ["core"],
        "base": ["core"],
        "faker": [],
        "mimesis": [],
    }
    if result["installer"]["available"]:
        assert "sqlseed-web[ai]" in items["ai"]["install_command"]
        assert "sqlseed[mimesis]" in items["mimesis"]["install_command"]
    assert items["base"]["install_command"] is None
    assert all(item["description"] and item["guidance"] for item in items.values())
    assert "sqlseed" in items["faker"]["guidance"] and "必需" in items["faker"]["guidance"]
    assert "AI" in items["cli"]["guidance"]
    assert not path.exists()


@pytest.mark.parametrize("tool", ["pip", "uv", None])
def test_installation_guidance_probes_available_tools_and_targets_serving_interpreter(
    settings_client: Any, monkeypatch: pytest.MonkeyPatch, tool: str | None
) -> None:
    client, _, path = settings_client
    executable = "/opt/sqlseed's env/python"
    uv = "/tools/uv bin/uv"
    probes: list[list[str]] = []
    monkeypatch.setattr(sys, "executable", executable)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda name: uv)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(time, "monotonic", lambda: {"pip": 0, "uv": 30, None: 60}[tool])

    def run(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        probes.append(arguments)
        assert arguments[-1] == "--version", "Only version probes may run while rendering installation guidance"
        assert 0 < kwargs["timeout"] <= 2
        ok = tool == "pip" if arguments[0] == executable else tool == "uv"
        return subprocess.CompletedProcess(arguments, 0 if ok else 1)

    monkeypatch.setattr(subprocess, "run", run)
    result = client.get("/api/settings/environment").json()
    assert result["installer"]["tool"] == tool
    assert result["installer"]["python_executable"] == executable
    assert result["installer"]["available"] is (tool is not None)
    assert result["installer"]["shell"] == "posix"
    items = {item["id"]: item for item in result["packages"] + result["providers"]}
    if tool:
        prefix = [executable, "-m", "pip"] if tool == "pip" else [uv, "pip"]
        target = [] if tool == "pip" else ["--python", executable]
        assert shlex.split(items["mimesis"]["install_command"]) == [*prefix, "install", *target, "sqlseed[mimesis]"]
        assert shlex.split(items["ai"]["repair_command"]) == [*prefix, "check", *target]
    else:
        assert all(item["install_command"] is None and item["repair_command"] is None for item in items.values())
        assert "未检测到" in result["installer"]["message"]
    assert items["base"]["install_command"] is None
    assert len(probes) == (1 if tool == "pip" else 2)
    assert not path.exists()


def test_windows_installation_guidance_uses_powershell_literals_for_paths(
    settings_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _ = settings_client
    executable = r"C:\Users\O'Brien\SQL Seed\python.exe"
    monkeypatch.setattr(sys, "executable", executable)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(time, "monotonic", lambda: 90)
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(args, 0))
    result = client.get("/api/settings/environment").json()
    mimesis = next(item for item in result["providers"] if item["id"] == "mimesis")
    assert result["installer"]["shell"] == "powershell"
    assert (
        mimesis["install_command"]
        == r"& 'C:\Users\O''Brien\SQL Seed\python.exe' '-m' 'pip' 'install' 'sqlseed[mimesis]'"
    )


def test_tool_probe_timeout_is_redacted_and_never_produces_an_install_command(
    settings_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _ = settings_client
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(time, "monotonic", lambda: 120)

    def timeout(args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(args, 1, output="private-tool-secret")

    monkeypatch.setattr(subprocess, "run", timeout)
    response = client.get("/api/settings/environment")
    result = response.json()
    assert result["installer"]["available"] is False
    assert all(item["install_command"] is None for item in result["packages"] + result["providers"])
    assert "private-tool-secret" not in response.text


def test_tool_probe_cache_expires_without_caching_package_versions(
    settings_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _ = settings_client
    executable, clock_value, pip_available = "/cache-test/python", [150.0], [True]
    probes: list[list[str]] = []
    monkeypatch.setattr(sys, "executable", executable)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(shutil, "which", lambda name: "/cache-test/uv")
    monkeypatch.setattr(time, "monotonic", lambda: clock_value[0])

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        probes.append(args)
        return subprocess.CompletedProcess(args, 0 if args[0].endswith("/uv") or pip_available[0] else 1)

    monkeypatch.setattr(subprocess, "run", run)
    first = client.get("/api/settings/environment").json()
    pip_available[0] = False
    clock_value[0] = 160.0
    second = client.get("/api/settings/environment").json()
    assert first["installer"]["tool"] == second["installer"]["tool"] == "pip"
    assert len(probes) == 1
    clock_value[0] = 181.0
    refreshed = client.get("/api/settings/environment").json()
    assert refreshed["installer"]["tool"] == "uv"
    assert len(probes) == 3
    for item in refreshed["packages"] + refreshed["providers"]:
        if item["installed"]:
            assert item["version"] == metadata.version(item["distribution"])


def test_missing_required_provider_is_an_environment_repair_not_optional_install(
    settings_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _ = settings_client
    original_version, original_import = metadata.version, importlib.import_module

    def version(name: str) -> str:
        if name == "Faker":
            raise metadata.PackageNotFoundError(name)
        return original_version(name)

    def import_module(name: str, package: str | None = None) -> Any:
        if name == "faker":
            raise ImportError("private-provider-secret")
        return original_import(name, package)

    monkeypatch.setattr(metadata, "version", version)
    monkeypatch.setattr(importlib, "import_module", import_module)
    response = client.get("/api/settings/environment")
    faker = next(item for item in response.json()["providers"] if item["id"] == "faker")
    assert faker["requirement"] == "required" and faker["status"] == "not_installed"
    assert "必需依赖缺失" in faker["guidance"] and "修复" in faker["guidance"]
    assert "private-provider-secret" not in response.text


@pytest.mark.parametrize("installed", [False, True])
def test_ai_settings_distinguish_missing_package_from_import_failure(
    settings_client: Any, monkeypatch: pytest.MonkeyPatch, installed: bool
) -> None:
    client, registry, path = settings_client
    original_import, original_version = builtins.__import__, metadata.version

    def import_module(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("sqlseed_ai"):
            raise ImportError("private-import-secret https://user:password@example.test")
        return original_import(name, *args, **kwargs)

    def version(name: str) -> str:
        if name == "sqlseed-ai":
            if not installed:
                raise metadata.PackageNotFoundError(name)
            return "9.8.7"
        return original_version(name)

    monkeypatch.setattr(builtins, "__import__", import_module)
    monkeypatch.setattr(metadata, "version", version)
    expected = "import_error" if installed else "not_installed"
    responses = [
        client.get("/api/workbench/ai/config"),
        client.post("/api/workbench/ai/config", json=configured()),
        client.post("/api/workbench/ai/test", json=configured()),
    ]
    assert [response.status_code for response in responses] == [200, 503, 200]
    for response in responses:
        result = response.json().get("detail", response.json())
        assert result["availability_status"] == expected
        assert result["available"] is False
        assert ("加载异常" if installed else "尚未安装") in result["message"]
        if installed:
            assert "尚未安装" not in result["message"]
        assert "private-import-secret" not in response.text and "password" not in response.text
    assert not path.exists() and registry.get_ai_override() == {}


def test_available_ai_settings_report_availability_independently_of_readiness(settings_client: Any) -> None:
    pytest.importorskip("sqlseed_ai")
    client, _, _ = settings_client
    result = client.get("/api/workbench/ai/config").json()
    assert result["availability_status"] == "available"
    assert result["available"] is True and result["ready"] is False


def test_missing_optional_packages_and_broken_imports_remain_readable(
    settings_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _ = settings_client
    original_version, original_import = metadata.version, importlib.import_module

    def version(name: str) -> str:
        if name in {"sqlseed-ai", "mimesis"}:
            raise metadata.PackageNotFoundError(name)
        if name == "mcp-server-sqlseed":
            return "1.0"  # This scenario is installed-but-broken, independent of the host's plugins.
        return original_version(name)

    def import_module(name: str, package: str | None = None) -> Any:
        if name.startswith(("sqlseed_ai", "mimesis")):
            raise ImportError("private-missing-secret")
        if name.startswith("mcp_server_sqlseed"):
            raise RuntimeError("private-broken-secret")
        return original_import(name, package)

    monkeypatch.setattr(metadata, "version", version)
    monkeypatch.setattr(importlib, "import_module", import_module)
    response = client.get("/api/settings/environment")
    assert response.status_code == 200
    result = response.json()
    packages = {item["id"]: item for item in result["packages"]}
    assert packages["ai"]["status"] == "not_installed" and packages["ai"]["available"] is False
    assert packages["mcp"]["status"] == "import_error" and packages["mcp"]["available"] is False
    assert "private-missing-secret" not in response.text
    assert "private-broken-secret" not in response.text
    assert client.get("/api/health").json() == {"status": "ok"}


def test_legacy_endpoints_share_saved_settings_and_scoped_credentials(
    settings_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sqlseed_ai")
    client, _, _ = settings_client
    monkeypatch.setenv("SQLSEED_AI_API_KEY", "private-env-key")
    monkeypatch.setenv("SQLSEED_AI_BASE_URL", configured()["base_url"])
    client.post("/api/workbench/ai/config", json=configured(base_url="https://new.example.test/v1"))
    legacy = client.get("/api/ai/config").json()
    assert legacy["effective"]["api_key_present"] is False
    assert client.get("/api/meta/ai").json()["api_key_present"] is False
    assert not any(key.startswith("_") for key in legacy["override"])
    requests = _record_model_requests(monkeypatch)
    assert client.post("/api/ai/test-connection").json()["ok"] is False
    assert_empty(requests, list)


def test_legacy_settings_cannot_transfer_session_secret_to_another_host(settings_client: Any) -> None:
    pytest.importorskip("sqlseed_ai")
    client, _, _ = settings_client
    client.post("/api/ai/config", json=configured(api_key="private-old-key"))
    moved = client.post("/api/ai/config", json=configured(base_url="https://new.example.test/v1"))
    assert moved.json()["effective"]["api_key_present"] is False
    assert client.get("/api/workbench/ai/config").json()["effective"]["api_key_present"] is False


def test_legacy_auto_heal_cannot_reuse_env_key_for_request_endpoint(
    settings_client: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sqlseed_ai")

    from sqlseed_ai import runtime

    _, registry, _ = settings_client
    path = tmp_path / "auto-heal.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    connection = registry.add_connection(str(path), provider="base")
    job = registry.create_job(connection.conn_id, "auto_heal", "credential isolation")
    monkeypatch.setenv("SQLSEED_AI_API_KEY", "private-env-key")
    monkeypatch.setenv("SQLSEED_AI_BASE_URL", configured()["base_url"])
    keys: list[str | None] = []

    def make_client(config: Any) -> Any:
        keys.append(config.resolve_api_key())
        raise RuntimeError("Unexpected SDK construction")

    monkeypatch.setattr(runtime, "build_llm_client", make_client)
    try:
        api._run_auto_heal_job(
            connection.conn_id,
            job.job_id,
            api.AutoHealRequest(base_url="https://other.example.test/v1", model="test-model"),
        )
        assert_empty(keys, list)
        assert "not configured" in registry.get_job(job.job_id).error
    finally:
        registry.close_connection(connection.conn_id)


def test_draft_return_to_environment_service_reuses_its_key_without_saving(
    settings_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sqlseed_ai")
    client, registry, path = settings_client
    monkeypatch.setenv("SQLSEED_AI_BASE_URL", configured()["base_url"])
    monkeypatch.setenv("SQLSEED_AI_API_KEY", "environment-service-key")
    client.post("/api/workbench/ai/config", json=configured(base_url="https://other.example.test/v1"))
    before_disk, before_memory = path.read_bytes(), registry.get_ai_override()
    requests: list[tuple[str, str]] = []

    def probe(url: str, **kwargs: Any) -> httpx.Response:
        requests.append((url, kwargs["headers"]["Authorization"]))
        return httpx.Response(200, json={"data": [{"id": "env-model"}]})

    monkeypatch.setattr(httpx, "get", probe)
    draft = client.post("/api/workbench/ai/test", json=configured())
    assert draft.json()["ok"] is True
    assert requests == [(configured()["base_url"] + "/models", "Bearer environment-service-key")]
    assert path.read_bytes() == before_disk and registry.get_ai_override() == before_memory
    saved = client.post("/api/workbench/ai/config", json=configured()).json()
    assert saved["effective"]["api_key_present"] is True
    assert saved["sources"]["api_key"] == "environment"
    assert client.post("/api/workbench/ai/test").json()["ok"] is True
    assert requests[-1] == requests[0]


def test_legacy_explicit_nulls_remove_prior_model_endpoint_and_secret(
    settings_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sqlseed_ai")
    client, registry, _ = settings_client
    client.post("/api/ai/config", json=configured(api_key="private-session-key"))
    # Model detection is a network boundary in the retained legacy endpoint.
    config_module = pytest.importorskip("sqlseed_ai.config")
    monkeypatch.setattr(config_module.AIConfig, "_detect_local_model", lambda self: None)
    response = client.post(
        "/api/ai/config", json={"backend": "ollama", "base_url": None, "model": None, "api_key": None}
    )
    assert response.status_code == 200
    result = client.get("/api/workbench/ai/config").json()
    assert result["effective"]["base_url"] == "http://localhost:11434/v1"
    assert result["effective"]["model"] == ""
    assert result["effective"]["api_key_present"] is False
    assert "private-session-key" not in registry.get_ai_override().values()


def test_legacy_null_fields_restore_environment_without_reusing_previous_key(
    settings_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sqlseed_ai")
    client, registry, _ = settings_client
    monkeypatch.setenv("SQLSEED_AI_MODEL", "environment-model")
    monkeypatch.setenv("SQLSEED_AI_BASE_URL", "https://environment.example.test/v1")
    monkeypatch.setenv("SQLSEED_AI_API_KEY", "environment-service-key")
    client.post("/api/ai/config", json=configured(api_key="previous-service-key"))
    response = client.post("/api/ai/config", json={"base_url": None, "model": None, "api_key": None})
    assert response.status_code == 200
    effective = client.get("/api/workbench/ai/config").json()
    assert effective["effective"]["base_url"] == "https://environment.example.test/v1"
    assert effective["effective"]["model"] == "environment-model"
    assert effective["sources"]["api_key"] == "environment"
    assert "previous-service-key" not in registry.get_ai_override().values()
    # An omitted endpoint field must keep the effective service during a model edit.
    edited = client.post("/api/ai/config", json={"model": "new-model"}).json()
    assert edited["effective"]["base_url"] == "https://environment.example.test/v1"
    assert edited["effective"]["model"] == "new-model"
