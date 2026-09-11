"""Uninstalled components stay unavailable even when editable code remains importable."""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Iterator
from importlib import metadata
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import create_model

from sqlseed_web import api, settings_environment, workbench_ai
from sqlseed_web.state import UIState


@pytest.mark.parametrize("incompatibility", ["config_fields", "call_signature", "runtime"])
def test_importable_legacy_ai_is_unavailable_before_any_model_request(
    component_client: Any, monkeypatch: pytest.MonkeyPatch, incompatibility: str
) -> None:
    original_import, original_version = importlib.import_module, metadata.version
    config = ModuleType("sqlseed_ai.config")
    fields = {"tool_calling_protocol": (str, "none"), "log_llm_interactions": (bool, False)}
    if incompatibility == "config_fields":
        fields.pop("tool_calling_protocol")
    config.AIConfig = create_model("InstalledConfig", **fields)
    analyzer = ModuleType("sqlseed_ai.analyzer")

    class Analyzer:
        def call_llm(self, messages: Any, *, stage: str = "") -> None:
            pytest.fail("Availability inspection must not call a model")

    if incompatibility == "call_signature":
        Analyzer.call_llm = lambda self, messages: pytest.fail("Must not call a legacy model")
    analyzer.SchemaAnalyzer = Analyzer

    def imported(name: str, package: str | None = None) -> Any:
        if name == "sqlseed_ai.config":
            return config
        if name == "sqlseed_ai.analyzer":
            return analyzer
        if name == "sqlseed_ai.runtime":
            if incompatibility == "runtime":
                raise ImportError("private-legacy-runtime")
            runtime = ModuleType(name)
            for factory in ("build_ai_config", "build_llm_client", "build_heal_orchestrator"):
                setattr(runtime, factory, lambda: pytest.fail("Inspection must not create AI services"))
            return runtime
        return original_import(name, package)

    monkeypatch.setattr(importlib, "import_module", imported)
    monkeypatch.setattr(metadata, "version", lambda name: "0.2.4" if name == "sqlseed-ai" else original_version(name))
    client = component_client[0]
    components = client.get("/api/settings/environment").json()["packages"]
    ai = next(component for component in components if component["id"] == "ai")
    assert ai["installed"] is True and ai["available"] is False
    assert ai["status"] == "import_error"
    result = client.get("/api/workbench/ai/config").json()
    assert result["available"] is False and result["recovery_action"] == "repair"
    response = client.post(
        "/api/workbench/ai/suggest",
        json={"conn_id": "unused", "schema_hash": "unused", "document": {}, "tables": ["users"]},
    )
    assert response.status_code == 503 and response.json()["detail"]["code"] == "ai_unavailable"
    assert "private-legacy-runtime" not in response.text


@pytest.fixture
def component_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, UIState, Path]]:
    registry = UIState()
    monkeypatch.setattr(api, "state", registry)
    monkeypatch.setattr(workbench_ai, "state", registry)
    preferences = tmp_path / "settings.json"
    monkeypatch.setenv("SQLSEED_WEB_SETTINGS_PATH", str(preferences))
    app = FastAPI()
    app.state.metadata_only = False
    app.include_router(settings_environment.router)
    app.include_router(api.router)
    app.include_router(workbench_ai.router)
    with TestClient(app) as client:
        yield client, registry, preferences


@pytest.fixture
def absent_optional_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    original = metadata.version

    def version(name: str) -> str:
        if name in {"sqlseed-ai", "mcp-server-sqlseed", "mimesis"}:
            raise metadata.PackageNotFoundError(name)
        return original(name)

    monkeypatch.setattr(metadata, "version", version)


def test_absent_metadata_wins_over_importable_editable_module(
    component_client: Any, absent_optional_metadata: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = component_client[0]
    original = importlib.import_module

    def loaded_module(name: str, package: str | None = None) -> Any:
        if name in {"sqlseed_ai.config", "mcp_server_sqlseed.server", "mimesis"}:
            return ModuleType(name)
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", loaded_module)
    result = client.get("/api/settings/environment").json()
    components = {item["id"]: item for item in result["packages"] + result["providers"]}
    for name in ("ai", "mcp", "mimesis"):
        assert components[name]["installed"] is False
        assert components[name]["available"] is False
        assert components[name]["status"] == "not_installed"


@pytest.fixture
def cached_ai_source(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Model an editable path inherited before uninstall, without installing a package."""
    source = Path(__file__).resolve().parents[2] / "sqlseed-ai" / "src"
    previous = {name for name in sys.modules if name == "sqlseed_ai" or name.startswith("sqlseed_ai.")}
    monkeypatch.syspath_prepend(str(source))
    importlib.import_module("sqlseed_ai.config")
    try:
        yield
    finally:
        for name in tuple(sys.modules):
            if (name == "sqlseed_ai" or name.startswith("sqlseed_ai.")) and name not in previous:
                sys.modules.pop(name, None)


def test_ai_uninstall_disables_cached_code_but_retains_ordinary_settings(
    component_client: Any, absent_optional_metadata: None, cached_ai_source: None
) -> None:
    client, registry, preferences = component_client
    saved = {"backend": "openai_compat", "model": "retained-model", "base_url": "https://service.test/v1"}
    preferences.write_text(json.dumps(saved))
    registry.set_ai_override({"api_key": "private-secret", "model": "session-model"})
    result = client.get("/api/workbench/ai/config").json()
    assert result["available"] is False and result["ready"] is False
    assert result["availability_status"] == "not_installed"
    assert result["effective"] == {**saved, "model": "session-model", "api_key_present": False}
    assert result["component_id"] == "ai" and result["recovery_action"] == "install"
    assert "private-secret" not in str(result)
    for url in ("/api/meta/ai", "/api/ai/config"):
        legacy = client.get(url).json()
        assert legacy["available"] is False
        assert legacy["availability_status"] == "not_installed"
    for url in ("/api/workbench/ai/test", "/api/ai/test-connection"):
        checked = client.post(url).json()
        assert checked["available"] is False
        assert checked["availability_status"] == "not_installed"
    for url, payload in (
        ("/api/workbench/ai/config", saved),
        (
            "/api/workbench/ai/suggest",
            {"conn_id": "unused", "schema_hash": "unused", "document": {}, "tables": ["users"]},
        ),
        ("/api/connections/unused/heal/auto", {}),
    ):
        response = client.post(url, json=payload)
        assert response.status_code == 503, response.text
        error = response.json()["detail"]
        assert error["code"] == "ai_unavailable" and error["recovery_action"] == "install"
    assert json.loads(preferences.read_text()) == saved
    assert registry.get_ai_override()["api_key"] == "private-secret"


def test_provider_list_does_not_trust_cached_core_availability(
    component_client: Any, absent_optional_metadata: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlseed.generators import registry

    monkeypatch.setattr(registry, "HAS_MIMESIS", True)
    result = component_client[0].get("/api/meta/providers").json()
    assert result["available"] == ["base", "faker"]
    assert result["statuses"]["mimesis"]["status"] == "not_installed"


def test_installed_broken_components_offer_repair_without_exposing_import_error(
    component_client: Any, cached_ai_source: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_version, original_import = metadata.version, importlib.import_module

    def version(name: str) -> str:
        return "1.0" if name in {"sqlseed-ai", "mimesis", "mcp-server-sqlseed"} else original_version(name)

    def broken(name: str, package: str | None = None) -> Any:
        if name in {"sqlseed_ai.config", "mimesis", "mcp_server_sqlseed.server"}:
            raise RuntimeError("private-password https://user:secret@example.test")
        return original_import(name, package)

    monkeypatch.setattr(metadata, "version", version)
    monkeypatch.setattr(importlib, "import_module", broken)
    client = component_client[0]
    result = client.get("/api/workbench/ai/config").json()
    assert result["availability_status"] == "import_error"
    assert result["recovery_action"] == "repair"
    assert result["available"] is False and "加载异常" in result["message"]
    assert "private-password" not in str(result) and "user:secret" not in str(result)
    packages = {item["id"]: item for item in client.get("/api/settings/environment").json()["packages"]}
    assert packages["mcp"]["status"] == "import_error" and packages["mcp"]["available"] is False
    statuses = client.get("/api/meta/providers").json()["statuses"]
    assert statuses["mimesis"]["status"] == "import_error"


def test_missing_ai_preferences_redact_credential_bearing_environment_url(
    component_client: Any, absent_optional_metadata: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SQLSEED_AI_BASE_URL", "https://user:private-password@example.test/v1?token=private-token")
    result = component_client[0].get("/api/workbench/ai/config").json()
    assert result["effective"]["base_url"] == ""
    assert "private-password" not in str(result) and "private-token" not in str(result)


@pytest.mark.parametrize("installed", [False, True])
def test_missing_provider_keeps_document_but_blocks_preview_with_recovery_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, installed: bool
) -> None:
    import sqlite3

    from sqlseed_web.workbench_runtime import check_document, normalize_document
    from sqlseed_web.workbench_schema import inspect_connection

    original_version, original_import = metadata.version, importlib.import_module

    def version(name: str) -> str:
        if name == "mimesis":
            if installed:
                return "1.0"
            raise metadata.PackageNotFoundError(name)
        return original_version(name)

    def broken(name: str, package: str | None = None) -> Any:
        if name == "mimesis":
            raise ImportError("private-provider-error")
        return original_import(name, package)

    monkeypatch.setattr(metadata, "version", version)
    monkeypatch.setattr(importlib, "import_module", broken)
    path = tmp_path / "provider.db"
    with sqlite3.connect(path) as database:
        database.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT)")
    registry = UIState()
    conn = registry.add_connection(str(path), provider="base")
    document = {"provider": "mimesis", "tables": [{"name": "users", "count": 2}]}
    try:
        normalized = normalize_document(conn, document)
        assert normalized["provider"] == "mimesis"
        result = check_document(conn, document, inspect_connection(conn)["schema_hash"], preview=True)
        assert result["ok"] is False and result["samples"] == {}
        issue = next(issue for issue in result["issues"] if issue["code"].startswith("provider_"))
        assert issue["code"] == ("provider_import_error" if installed else "provider_not_installed")
        assert issue["component_id"] == "mimesis"
        assert issue["recovery_action"] == ("repair" if installed else "install")
        assert "private-provider-error" not in str(result)
        assert conn.orchestrator.get_row_count("users") == 0
    finally:
        registry.close_connection(conn.conn_id)
