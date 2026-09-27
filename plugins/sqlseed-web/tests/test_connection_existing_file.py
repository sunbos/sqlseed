"""The file-selection flow must not create a database from a mistyped path."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.sqlite_helpers import sqlite_connection

from sqlseed_web import api
from sqlseed_web import state as state_module
from sqlseed_web.state import UIState
from sqlseed_web.workbench_schema import inspect_connection


@pytest.fixture(name="client")
def fixture_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    registry = UIState()
    monkeypatch.setattr(api, "state", registry)
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        yield client
    for connection in registry.list_connections():
        registry.close_connection(connection["conn_id"])


@pytest.mark.parametrize("directory", [False, True])
def test_selected_missing_file_or_directory_is_rejected_without_creation(
    client: TestClient, tmp_path: Path, directory: bool
) -> None:
    path = tmp_path / "not a database & missing.db"
    if directory:
        path.mkdir()
    response = client.post(
        "/api/connections", json={"db_path": str(path), "provider": "base", "require_existing": True}
    )
    assert response.status_code == 400
    assert "请选择已有" in response.json()["detail"]
    assert path.is_dir() if directory else not path.exists()
    assert client.get("/api/connections").json()["connections"] == []


def test_legacy_api_retains_explicit_database_creation(client: TestClient, tmp_path: Path) -> None:
    path = tmp_path / "legacy-new.db"
    response = client.post("/api/connections", json={"db_path": str(path), "provider": "base"})
    assert response.status_code == 200
    assert response.json()["tables"] == []
    assert path.is_file()


@pytest.mark.parametrize("as_uri", [False, True])
def test_existing_special_character_file_keeps_contents_and_connection_identity(
    client: TestClient, tmp_path: Path, as_uri: bool
) -> None:
    path = tmp_path / "中文 orders & %41 #.db"
    with sqlite_connection(path) as db:
        db.executescript("CREATE TABLE items(id INTEGER PRIMARY KEY, value INTEGER); INSERT INTO items VALUES(1, 7)")
    target = f"sqlite:///{path.as_uri()}?uri=true&mode=rwc" if as_uri else str(path)
    original = api.state.add_connection(target, provider="base")
    response = client.post("/api/connections", json={"db_path": target, "provider": "base", "require_existing": True})
    assert response.status_code == 200, response.text
    selected = api.state.get_connection(response.json()["conn_id"])
    assert selected.target == target
    assert selected.orchestrator.query("SELECT value FROM items") == [{"value": 7}]
    assert inspect_connection(selected)["target_key"] == inspect_connection(original)["target_key"]
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("mode", ["mode=ro", "immutable=1"])
def test_existing_uri_readonly_options_are_not_relaxed(client: TestClient, tmp_path: Path, mode: str) -> None:
    path = tmp_path / "readonly.db"
    with sqlite_connection(path) as db:
        db.executescript("CREATE TABLE items(id INTEGER PRIMARY KEY); INSERT INTO items VALUES(1)")
    response = client.post(
        "/api/connections",
        json={"url": f"sqlite:///{path.as_uri()}?uri=true&{mode}", "provider": "base", "require_existing": True},
    )
    assert response.status_code == 200, response.text
    connection = api.state.get_connection(response.json()["conn_id"])
    assert connection.orchestrator.query("SELECT id FROM items") == [{"id": 1}]
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        connection.orchestrator.execute("INSERT INTO items VALUES(2)")
    assert connection.orchestrator.query("SELECT id FROM items") == [{"id": 1}]


@pytest.mark.parametrize("mode", ["mode=invalid", "mode=ro&mode=rwc"])
def test_invalid_uri_mode_is_not_silently_replaced_with_write_access(
    client: TestClient, tmp_path: Path, mode: str
) -> None:
    path = tmp_path / "invalid-mode.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY)")
    response = client.post(
        "/api/connections",
        json={"url": f"sqlite:///{path.as_uri()}?uri=true&{mode}", "provider": "base", "require_existing": True},
    )
    assert response.status_code == 400
    assert client.get("/api/connections").json()["connections"] == []
    with sqlite_connection(path) as db:
        assert db.execute("SELECT count(*) FROM items").fetchone()[0] == 0


def test_file_removed_between_validation_and_open_is_not_recreated(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "removed-before-open.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY)")
    real_orchestrator = state_module.DataOrchestrator

    def remove_before_open(target: str, **kwargs: Any) -> Any:
        path.unlink()
        return real_orchestrator(target, **kwargs)

    monkeypatch.setattr(state_module, "DataOrchestrator", remove_before_open)
    response = client.post(
        "/api/connections", json={"db_path": str(path), "provider": "base", "require_existing": True}
    )
    assert response.status_code == 400
    assert not path.exists()
    assert client.get("/api/connections").json()["connections"] == []


@pytest.mark.parametrize("target", [":memory:", "sqlite:///file:selection-memory?mode=memory&cache=shared&uri=true"])
def test_explicit_memory_connections_keep_their_semantics(target: str) -> None:
    registry = UIState()
    connection = registry.add_connection(target, provider="base", require_existing=True)
    try:
        assert connection.target == target
        assert connection.orchestrator.get_table_names() == []
    finally:
        registry.close_connection(connection.conn_id)
