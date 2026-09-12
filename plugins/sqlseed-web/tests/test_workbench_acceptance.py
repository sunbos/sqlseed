"""Full HTTP workbench journeys with isolated metadata and real temporary databases."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient
from tests.sqlite_helpers import sqlite_connection

from sqlseed_web import api, workbench
from sqlseed_web.app import create_app
from sqlseed_web.state import UIState

from .workbench_test_helpers import parent_child_document

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(name="workspace_client")
def fixture_workspace_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    registry = UIState()
    monkeypatch.setattr(api, "state", registry)
    monkeypatch.setattr(workbench, "state", registry)
    monkeypatch.setenv("SQLSEED_WEB_WORKSPACE_PATH", str(tmp_path / "workspace-metadata.sqlite3"))
    monkeypatch.setenv("SQLSEED_AI_ENABLED", "0")
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        yield client
    deadline = time.monotonic() + 10
    while any(job.status == "running" for job in registry.recent_jobs()) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert all(job.status != "running" for job in registry.recent_jobs()), "Worker did not release its reservation"
    for connection in registry.list_connections():
        registry.close_connection(connection["conn_id"])


@pytest.fixture(name="target_path")
def fixture_target_path(tmp_path: Path) -> Path:
    path = tmp_path / "target.sqlite3"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE parents (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE);"
            "CREATE TABLE children (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "parent_id INTEGER NOT NULL REFERENCES parents(id), amount INTEGER NOT NULL, doubled INTEGER NOT NULL);"
        )
    return path


def _connect(client: TestClient, path: Path) -> tuple[str, dict[str, Any]]:
    response = client.post("/api/connections", json={"db_path": str(path), "provider": "base", "locale": "zh_CN"})
    assert response.status_code == 200, response.text
    conn_id = response.json()["conn_id"]
    response = client.get(f"/api/workbench/connections/{conn_id}/schema")
    assert response.status_code == 200, response.text
    return conn_id, response.json()


def _document() -> dict[str, Any]:
    return parent_child_document("base", child_batch_size=2)


def _save(client: TestClient, conn_id: str, schema: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        "/api/workbench/drafts",
        json={
            "conn_id": conn_id,
            "name": "HTTP 验收草稿",
            "schema_hash": schema["schema_hash"],
            "document": document,
            "view_state": {"table": "children", "page": "graph", "graphMode": "paths"},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _check(client: TestClient, conn_id: str, draft: dict[str, Any], endpoint: str = "check") -> dict[str, Any]:
    response = client.post(
        f"/api/workbench/{endpoint}",
        json={"conn_id": conn_id, "document": draft["document"], "schema_hash": draft["schema_hash"], "count": 3},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _run_request(conn_id: str, draft: dict[str, Any], checked: dict[str, Any]) -> dict[str, Any]:
    return {
        "conn_id": conn_id,
        "draft_id": draft["id"],
        "revision": draft["revision"],
        "schema_hash": draft["schema_hash"],
        "config_hash": checked["config_hash"],
    }


def _poll(client: TestClient, run_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(f"/api/workbench/runs/{run_id}")
        assert response.status_code == 200, response.text
        run = response.json()
        if run["status"] not in {"queued", "running"}:
            return run
        time.sleep(0.01)
    return pytest.fail("Persistent run did not reach a terminal state")


def test_http_save_reopen_check_preview_run_and_history(workspace_client: TestClient, target_path: Path) -> None:
    client = workspace_client
    conn_id, schema = _connect(client, target_path)
    original = _document()
    draft = _save(client, conn_id, schema, original)
    assert "db_path" not in draft["document"] and "url" not in draft["document"]
    original["tables"][0]["count"] = 99

    reopened = client.get(f"/api/workbench/drafts/{draft['id']}")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["document"]["tables"][0]["count"] == 4
    assert reopened.json()["view_state"]["graphMode"] == "paths"
    checked = _check(client, conn_id, draft)
    preview = _check(client, conn_id, draft, "preview")
    assert checked["ok"] and preview["ok"], (checked, preview)
    assert checked["order"] == ["parents", "children"]
    assert not preview["preview_complete"]
    assert len(preview["samples"]["parents"]) == 3
    with sqlite_connection(target_path) as db:
        assert db.execute("SELECT COUNT(*) FROM parents").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM children").fetchone()[0] == 0

    started = client.post("/api/workbench/runs", json=_run_request(conn_id, draft, checked))
    assert started.status_code == 202, started.text
    run = _poll(client, started.json()["id"])
    assert run["status"] == "done", run
    assert run["rows_inserted"] == 7
    assert run["document"] == draft["document"]
    assert [(table["name"], table["rows_inserted"]) for table in run["tables"]] == [("parents", 3), ("children", 4)]
    history = client.get("/api/workbench/runs")
    assert history.status_code == 200, history.text
    assert history.json()[0]["id"] == run["id"]
    assert history.json()[0]["status"] == "done"
    with TestClient(create_app(), raise_server_exceptions=False) as reopened_client:
        assert reopened_client.get(f"/api/workbench/runs/{run['id']}").json()["rows_inserted"] == 7
    with sqlite_connection(target_path) as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM children JOIN parents ON parents.id=children.parent_id "
                "WHERE amount=7 AND doubled=14"
            ).fetchone()[0]
            == 4
        )
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_http_run_rejects_stale_draft_revision_and_target(
    workspace_client: TestClient, target_path: Path, tmp_path: Path
) -> None:
    client = workspace_client
    conn_id, schema = _connect(client, target_path)
    draft = _save(client, conn_id, schema, _document())
    checked = _check(client, conn_id, draft)
    updated = client.put(
        f"/api/workbench/drafts/{draft['id']}",
        json={
            "conn_id": conn_id,
            "name": "新版本",
            "schema_hash": draft["schema_hash"],
            "document": draft["document"],
            "revision": draft["revision"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == 2
    stale = client.post("/api/workbench/runs", json=_run_request(conn_id, draft, checked))
    assert stale.status_code == 409, stale.text

    other = tmp_path / "other.sqlite3"
    with sqlite_connection(other) as db:
        db.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    other_id, _ = _connect(client, other)
    mismatch = client.post("/api/workbench/runs", json=_run_request(other_id, updated.json(), checked))
    assert mismatch.status_code == 409, mismatch.text
    assert client.get("/api/workbench/runs").json() == []
    with sqlite_connection(target_path) as db:
        assert db.execute("SELECT COUNT(*) FROM parents").fetchone()[0] == 0


def test_http_run_rechecks_schema_and_parent_data_after_check(workspace_client: TestClient, target_path: Path) -> None:
    client = workspace_client
    conn_id, schema = _connect(client, target_path)
    draft = _save(client, conn_id, schema, _document())
    checked = _check(client, conn_id, draft)
    with sqlite_connection(target_path) as db:
        db.execute("INSERT INTO parents (code) VALUES ('external-row')")
    stale = client.post("/api/workbench/runs", json=_run_request(conn_id, draft, checked))
    assert stale.status_code == 409, stale.text
    fresh = _check(client, conn_id, draft)
    with sqlite_connection(target_path) as db:
        db.execute("ALTER TABLE children ADD COLUMN external_change TEXT")
    changed = client.post("/api/workbench/runs", json=_run_request(conn_id, draft, fresh))
    assert changed.status_code == 409, changed.text
    assert client.get("/api/workbench/runs").json() == []
    with sqlite_connection(target_path) as db:
        assert db.execute("SELECT COUNT(*) FROM parents").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM children").fetchone()[0] == 0


def test_http_partial_failure_persists_actual_rows_and_unstarted_tables(
    workspace_client: TestClient, target_path: Path
) -> None:
    with sqlite_connection(target_path) as db:
        db.executescript(
            "CREATE TRIGGER reject_later BEFORE INSERT ON parents "
            "WHEN (SELECT COUNT(*) FROM parents) >= 2 "
            "BEGIN SELECT RAISE(ABORT, 'second batch rejected'); END;"
        )
    client = workspace_client
    conn_id, schema = _connect(client, target_path)
    document = _document()
    document["tables"][1].update(count=4, batch_size=2)
    draft = _save(client, conn_id, schema, document)
    checked = _check(client, conn_id, draft)
    assert checked["ok"], checked
    started = client.post("/api/workbench/runs", json=_run_request(conn_id, draft, checked))
    assert started.status_code == 202, started.text
    run = _poll(client, started.json()["id"])
    assert run["status"] == "error", run
    assert run["rows_inserted"] == 2
    assert run["tables"][0]["rows_inserted"] == 2
    assert run["tables"][0]["batch_count"] == 1
    assert run["tables"][1]["status"] == "not_run"
    assert run["errors"]
    with sqlite_connection(target_path) as db:
        assert db.execute("SELECT COUNT(*) FROM parents").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM children").fetchone()[0] == 0
