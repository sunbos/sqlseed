"""Configuration lifecycle preserves complete snapshots on real workspace SQLite."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from sqlseed_web.app import create_app
from sqlseed_web.workbench_store import RevisionConflict, WorkspaceStore, get_store


def payload() -> dict[str, Any]:
    return {
        "name": "中文配置",
        "target_key": "target-A",
        "target_label": "application.db",
        "schema_hash": "schema-A",
        "document": {
            "provider": "base",
            "locale": "zh_CN",
            "optimize_pragma": False,
            "tables": [{"name": "users", "count": 3, "seed": 0, "columns": []}],
            "custom_column_mappings": {"exact": {"code": {"generator": "uuid", "params": {}}}},
        },
        "view_state": {"table": "users", "tableDrafts": {"unselected": {"count": 7}}},
    }


@pytest.fixture()
def store(tmp_path: Path) -> WorkspaceStore:
    return WorkspaceStore(tmp_path / "workspace.sqlite3")


def test_rename_updates_only_metadata_with_revision(store: WorkspaceStore) -> None:
    original = store.save_draft(payload())
    renamed = store.rename_draft(original["id"], "新名称", expected_revision=1)
    assert renamed["name"] == "新名称"
    assert renamed["revision"] == 2
    for key in ("id", "document", "schema_hash", "target_key", "target_label", "view_state"):
        assert renamed[key] == original[key]
    with pytest.raises(RevisionConflict):
        store.rename_draft(original["id"], "旧界面名称", expected_revision=1)
    assert store.get_draft(original["id"]) == renamed


def test_copy_is_detached_new_configuration_preserving_advanced_data(store: WorkspaceStore) -> None:
    original = store.save_draft(payload())
    copied = store.copy_draft(original["id"], "副本", expected_revision=1)
    assert copied["id"] != original["id"]
    assert copied["name"] == "副本"
    assert copied["revision"] == 1
    for key in ("document", "schema_hash", "target_key", "target_label", "view_state"):
        assert copied[key] == original[key]
    copied["document"]["tables"][0]["count"] = 99
    assert store.get_draft(copied["id"])["document"]["tables"][0]["count"] == 3
    assert store.get_draft(original["id"]) == original


@pytest.mark.parametrize("status", ["queued", "running", "done"])
def test_delete_leaves_run_snapshots_and_progress_independent(store: WorkspaceStore, status: str) -> None:
    original = store.save_draft(payload())
    run = store.create_run(
        {**original, "id": "run-A", "draft_id": original["id"], "status": status}, require_current_draft=True
    )
    result = store.delete_draft(original["id"], expected_revision=1)
    assert result == {"id": original["id"], "revision": 1, "deleted": True}
    with pytest.raises(KeyError):
        store.get_draft(original["id"])
    assert store.list_drafts() == []
    assert store.get_run("run-A") == run
    assert store.update_run("run-A", {"rows_inserted": 2})["rows_inserted"] == 2


@pytest.mark.parametrize("operation", ["delete", "copy", "rename"])
def test_lifecycle_rejects_stale_revision_without_changes(store: WorkspaceStore, operation: str) -> None:
    original = store.save_draft(payload())
    current = store.save_draft(payload(), draft_id=original["id"], expected_revision=1)
    method = getattr(store, f"{operation}_draft")
    args = [original["id"]] if operation == "delete" else [original["id"], "变更"]
    with pytest.raises(RevisionConflict):
        method(*args, expected_revision=1)
    assert store.list_drafts() == [current]


def test_run_creation_racing_delete_never_loses_accepted_snapshot(store: WorkspaceStore) -> None:
    original = store.save_draft(payload())

    def create() -> str:
        try:
            store.create_run({**original, "id": "accepted-run", "draft_id": original["id"]}, require_current_draft=True)
            return "accepted"
        except KeyError:
            return "deleted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        run = pool.submit(create)
        deleted = pool.submit(store.delete_draft, original["id"], expected_revision=1)
        assert deleted.result()["deleted"] is True
        outcome = run.result()
    assert not store.list_drafts()
    if outcome == "accepted":
        assert store.get_run("accepted-run")["document"] == original["document"]
    else:
        assert store.list_runs() == []


@pytest.fixture()
def lifecycle_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, dict[str, Any], Path]]:
    target = tmp_path / "user-data.sqlite3"
    with sqlite3.connect(target) as db:
        db.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT); INSERT INTO users VALUES(1, 'Keep');")
    monkeypatch.setenv("SQLSEED_WEB_WORKSPACE_PATH", str(tmp_path / "metadata.sqlite3"))
    draft = get_store().save_draft({**payload(), "target_label": str(target)})
    with TestClient(create_app()) as client:
        yield client, draft, target


def test_metadata_endpoints_work_without_connection_and_never_touch_business_rows(lifecycle_client: Any) -> None:
    client, draft, target = lifecycle_client
    base = f"/api/workbench/drafts/{draft['id']}"
    copied = client.post(base + "/copy", json={"revision": 1, "name": "保留完整规则"})
    assert copied.status_code == 200, copied.text
    assert copied.json()["id"] != draft["id"]
    assert copied.json()["document"] == draft["document"]
    renamed = client.patch(base, json={"revision": 1, "name": "  新名称  "})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "新名称"
    assert renamed.json()["revision"] == 2
    conflict = client.delete(base + "?revision=1")
    assert conflict.status_code == 409
    assert client.get(base).json()["name"] == "新名称"
    deleted = client.delete(base + "?revision=2")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"id": draft["id"], "revision": 2, "deleted": True}
    assert client.get(base).status_code == 404
    assert client.get(f"/api/workbench/drafts/{copied.json()['id']}").status_code == 200
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT * FROM users").fetchall() == [(1, "Keep")]


def test_export_works_offline_and_round_trips_saved_document(lifecycle_client: Any) -> None:
    client, draft, _ = lifecycle_client
    response = client.get(f"/api/workbench/drafts/{draft['id']}/export")
    assert response.status_code == 200, response.text
    exported = response.json()
    assert exported["json"] == draft["document"]
    assert yaml.safe_load(exported["yaml"]) == draft["document"]
    assert exported["revision"] == draft["revision"]
    assert "db_path" not in exported["json"]
    assert "target_label" not in exported["json"]


def test_accepted_worker_finishes_from_snapshot_after_configuration_is_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: WorkspaceStore
) -> None:
    from sqlseed_web import workbench_runtime
    from sqlseed_web.state import UIState
    from sqlseed_web.workbench_schema import inspect_connection

    target = tmp_path / "running.sqlite3"
    with sqlite3.connect(target) as db:
        db.execute("CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT, amount INTEGER NOT NULL)")
    registry = UIState()
    connection = registry.add_connection(str(target), provider="base")
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    execute = workbench_runtime.execute_run

    def gated_execute(*args: Any, **kwargs: Any) -> None:
        entered.set()
        try:
            if not release.wait(5):
                raise RuntimeError("Test did not release accepted worker")
            execute(*args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(workbench_runtime, "execute_run", gated_execute)
    try:
        schema = inspect_connection(connection)
        document = workbench_runtime.normalize_document(
            connection,
            {
                "provider": "base",
                "locale": "en_US",
                "optimize_pragma": False,
                "tables": [
                    {
                        "name": "users",
                        "count": 3,
                        "columns": [
                            {"name": "amount", "generator": "integer", "params": {"min_value": 8, "max_value": 8}},
                        ],
                    }
                ],
            },
        )
        draft = store.save_draft(
            {
                **payload(),
                "document": document,
                "target_key": schema["target_key"],
                "target_label": schema["target_label"],
                "schema_hash": schema["schema_hash"],
            }
        )
        checked = workbench_runtime.check_document(connection, document, schema["schema_hash"])
        assert checked["ok"], checked
        run = workbench_runtime.start_run(
            connection.conn_id,
            draft["id"],
            1,
            schema["schema_hash"],
            checked["config_hash"],
            registry=registry,
            store=store,
        )
        assert entered.wait(5)
        store.delete_draft(draft["id"], expected_revision=1)
        release.set()
        assert finished.wait(5)
        result = store.get_run(run["id"])
        assert result["status"] == "done", result
        assert result["rows_inserted"] == 3
        assert result["document"] == document
        with sqlite3.connect(target) as db:
            assert db.execute("SELECT id, amount FROM users ORDER BY id").fetchall() == [(1, 8), (2, 8), (3, 8)]
    finally:
        release.set()
        if entered.is_set():
            assert finished.wait(5)
        registry.close_connection(connection.conn_id)


@pytest.mark.parametrize(
    "method, suffix, body",
    [
        ("delete", "", None),
        ("delete", "?revision=0", None),
        ("patch", "", {"revision": 1, "name": "   "}),
        ("patch", "", {"revision": True, "name": "Wrong revision"}),
        ("post", "/copy", {"revision": 1, "name": "x" * 201}),
    ],
)
def test_invalid_lifecycle_request_keeps_original(lifecycle_client: Any, method: str, suffix: str, body: Any) -> None:
    client, draft, _ = lifecycle_client
    url = f"/api/workbench/drafts/{draft['id']}"
    kwargs = {"json": body} if body is not None else {}
    response = getattr(client, method)(url + suffix, **kwargs)
    assert response.status_code == 422, response.text
    assert client.get(url).json() == draft


@pytest.mark.parametrize(
    "method, suffix, body",
    [
        ("delete", "?revision=1", None),
        ("patch", "", {"revision": 1, "name": "New name"}),
        ("post", "/copy", {"revision": 1, "name": "Copy"}),
        ("get", "/export", None),
    ],
)
def test_missing_lifecycle_target_returns_not_found(lifecycle_client: Any, method: str, suffix: str, body: Any) -> None:
    client, _, _ = lifecycle_client
    kwargs = {"json": body} if body is not None else {}
    response = getattr(client, method)("/api/workbench/drafts/missing" + suffix, **kwargs)
    assert response.status_code == 404, response.text
