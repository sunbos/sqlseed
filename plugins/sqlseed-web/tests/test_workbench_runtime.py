"""The workbench validates and executes real SQLite plans without AI."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from sqlseed_web.state import Connection, UIState


@pytest.fixture()
def connection(tmp_path: Path) -> Iterator[Connection]:
    path = tmp_path / "workbench.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(
            "CREATE TABLE parents (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE);"
            "CREATE TABLE children (id INTEGER PRIMARY KEY AUTOINCREMENT, parent_id INTEGER NOT NULL "
            "REFERENCES parents(id), amount INTEGER NOT NULL, doubled INTEGER NOT NULL);"
            "CREATE TABLE later (id INTEGER PRIMARY KEY, value INTEGER NOT NULL);"
        )
    registry = UIState()
    conn = registry.add_connection(str(path), provider="base")
    yield conn
    registry.close_connection(conn.conn_id)


def document() -> dict[str, Any]:
    return {
        "provider": "faker",
        "locale": "zh_CN",
        "optimize_pragma": False,
        "tables": [
            {
                "name": "children",
                "count": 4,
                "seed": 0,
                "columns": [
                    {"name": "amount", "generator": "integer", "params": {"min_value": 7, "max_value": 7}},
                    {"name": "doubled", "derive_from": "amount", "expression": "value * 2"},
                ],
            },
            {"name": "parents", "count": 3, "columns": [{"name": "code", "generator": "uuid"}]},
        ],
    }


def test_empty_planned_parent_passes_check_but_preview_is_explicitly_partial(connection: Connection) -> None:
    from sqlseed_web.workbench_runtime import check_document
    from sqlseed_web.workbench_schema import inspect_connection

    schema = inspect_connection(connection)
    result = check_document(connection, document(), schema["schema_hash"], preview=True)
    assert result["ok"], result
    assert result["order"] == ["parents", "children"]
    assert result["layers"] == [["parents"], ["children"]]
    assert result["preview_complete"] is False
    assert result["samples"]["parents"]
    assert result["samples"].get("children", []) == []
    assert any(issue["code"] == "preview_requires_parent" for issue in result["issues"])
    assert connection.orchestrator.get_row_count("parents") == 0
    assert connection.orchestrator.get_row_count("children") == 0


@pytest.mark.parametrize("section", ["root", "table"])
def test_unknown_config_fields_do_not_silently_disappear(connection: Connection, section: str) -> None:
    from sqlseed_web.workbench_runtime import WorkbenchError, normalize_document

    config = document()
    if section == "root":
        config["silent_typo"] = True
    else:
        config["tables"][0]["silent_typo"] = True
    with pytest.raises(WorkbenchError, match="silent_typo"):
        normalize_document(connection, config)


def test_invalid_target_generator_column_and_schema_are_rejected(connection: Connection) -> None:
    from sqlseed_web.workbench_runtime import WorkbenchError, check_document, normalize_document
    from sqlseed_web.workbench_schema import inspect_connection

    with pytest.raises(WorkbenchError, match="目标"):
        normalize_document(connection, {**document(), "db_path": "/other.db"})
    schema = inspect_connection(connection)
    config = document()
    config["tables"][0]["columns"] = [{"name": "gone", "generator": "imaginary"}]
    result = check_document(connection, config, schema["schema_hash"])
    assert not result["ok"]
    codes = {issue["code"] for issue in result["issues"]}
    assert {"unknown_generator", "unknown_column"} <= codes
    stale = check_document(connection, document(), "old hash")
    assert not stale["ok"]
    assert any(issue["code"] == "schema_changed" for issue in stale["issues"])


def test_not_null_empty_parent_outside_plan_blocks(connection: Connection) -> None:
    from sqlseed_web.workbench_runtime import check_document
    from sqlseed_web.workbench_schema import inspect_connection

    config = document()
    config["tables"] = config["tables"][:1]
    result = check_document(connection, config, inspect_connection(connection)["schema_hash"])
    assert not result["ok"]
    assert any(issue["code"] == "missing_parent_source" for issue in result["issues"])


def run_plan(conn: Connection, config: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    from sqlseed_web.workbench_runtime import check_document, normalize_document, start_run
    from sqlseed_web.workbench_schema import inspect_connection
    from sqlseed_web.workbench_store import WorkspaceStore

    registry = UIState()
    worker_conn = registry.add_connection(conn.target, provider="base")
    store = WorkspaceStore(tmp_path / "history.db")
    schema = inspect_connection(worker_conn)
    normalized = normalize_document(worker_conn, config)
    draft = store.save_draft(
        {
            "name": "plan",
            "target_key": schema["target_key"],
            "target_label": schema["target_label"],
            "document": normalized,
            "schema_hash": schema["schema_hash"],
            "view_state": {},
        }
    )
    check = check_document(worker_conn, normalized, schema["schema_hash"])
    assert check["ok"], check
    run = start_run(
        worker_conn.conn_id,
        draft["id"],
        draft["revision"],
        schema["schema_hash"],
        check["config_hash"],
        registry=registry,
        store=store,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        saved = store.get_run(run["id"])
        if saved["status"] in {"done", "error"} and all(job.status != "running" for job in registry.recent_jobs()):
            registry.close_connection(worker_conn.conn_id)
            return saved
        time.sleep(0.01)
    pytest.fail("run did not terminate")


def test_run_executes_saved_parent_first_plan_with_derived_columns(connection: Connection, tmp_path: Path) -> None:
    run = run_plan(connection, document(), tmp_path)
    assert run["status"] == "done", run
    assert run["rows_inserted"] == 7
    assert [table["name"] for table in run["tables"]] == ["parents", "children"]
    with closing(sqlite3.connect(connection.target)) as db, db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM children JOIN parents ON parents.id = children.parent_id WHERE amount=7 AND doubled=14"
            ).fetchone()[0]
            == 4
        )
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_partial_failure_stops_later_tables_and_reports_committed_batches(
    connection: Connection, tmp_path: Path
) -> None:
    with closing(sqlite3.connect(connection.target)) as db, db:
        db.executescript(
            "CREATE TRIGGER reject_later BEFORE INSERT ON parents WHEN (SELECT COUNT(*) FROM parents) >= 2 BEGIN SELECT RAISE(ABORT, 'second batch rejected'); END;"
        )
    config = document()
    config["tables"][1].update(count=4, batch_size=2)
    config["tables"].append({"name": "later", "count": 1})
    run = run_plan(connection, config, tmp_path)
    assert run["status"] == "error", run
    assert run["rows_inserted"] == 2
    by_name = {table["name"]: table for table in run["tables"]}
    assert by_name["parents"]["rows_inserted"] == 2
    assert by_name["parents"]["batch_count"] == 1
    assert by_name["children"]["status"] == "not_run"
    assert by_name["later"]["status"] == "not_run"


def test_export_removes_password_without_changing_document(connection: Connection) -> None:
    from sqlseed_web.workbench_runtime import export_document

    conn = Connection(
        "url", "postgresql://user:private@db.local/example?sslpassword=hidden", "base", "en_US", connection.orchestrator
    )
    exported = export_document(conn, document())
    assert exported["credentials_omitted"] is True
    assert "private" not in exported["json"]
    assert "hidden" not in exported["json"]


def test_cross_table_cycle_and_column_cycle_are_rejected(connection: Connection) -> None:
    from sqlseed_web.workbench_runtime import check_document
    from sqlseed_web.workbench_schema import inspect_connection

    with closing(sqlite3.connect(connection.target)) as db, db:
        db.executescript(
            "CREATE TABLE a(id INTEGER PRIMARY KEY, bid INTEGER REFERENCES b(id)); CREATE TABLE b(id INTEGER PRIMARY KEY, aid INTEGER REFERENCES a(id));"
        )
    schema = inspect_connection(connection)
    cycle = check_document(connection, {"tables": [{"name": "a"}, {"name": "b"}]}, schema["schema_hash"])
    assert any(issue["code"] == "cross_table_cycle" for issue in cycle["issues"])
    config = document()
    config["tables"][0]["columns"] = [
        {"name": "amount", "derive_from": "doubled", "expression": "value"},
        {"name": "doubled", "derive_from": "amount", "expression": "value"},
    ]
    derived = check_document(connection, config, schema["schema_hash"])
    assert not derived["ok"]
    assert any(issue["code"] == "generation_invalid" for issue in derived["issues"])


def test_router_draft_roundtrip_and_stale_revision_returns_conflict(
    connection: Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from sqlseed_web import workbench
    from sqlseed_web.workbench_store import WorkspaceStore

    registry = UIState()
    conn = registry.add_connection(connection.target, provider="base")
    store = WorkspaceStore(tmp_path / "router.db")
    monkeypatch.setattr(workbench, "state", registry)
    monkeypatch.setattr(workbench, "get_store", lambda: store)
    app = FastAPI()
    app.include_router(workbench.router)
    with TestClient(app, raise_server_exceptions=False) as client:
        schema = client.get(f"/api/workbench/connections/{conn.conn_id}/schema").json()
        body = {"conn_id": conn.conn_id, "name": "draft", "document": document(), "schema_hash": schema["schema_hash"]}
        saved = client.post("/api/workbench/drafts", json=body)
        assert saved.status_code == 200, saved.text
        draft = saved.json()
        assert "url" not in draft["document"]
        changed = client.put(f"/api/workbench/drafts/{draft['id']}", json={**body, "revision": draft["revision"]})
        assert changed.status_code == 200, changed.text
        stale = client.put(f"/api/workbench/drafts/{draft['id']}", json={**body, "revision": draft["revision"]})
        assert stale.status_code == 409, stale.text
        check = client.post(
            "/api/workbench/check",
            json={"conn_id": conn.conn_id, "document": document(), "schema_hash": schema["schema_hash"]},
        ).json()
        denied = client.post(
            "/api/workbench/runs",
            json={
                "conn_id": conn.conn_id,
                "draft_id": draft["id"],
                "revision": draft["revision"],
                "schema_hash": schema["schema_hash"],
                "config_hash": check["config_hash"],
            },
        )
        assert denied.status_code == 409, denied.text
        invalid = client.post(
            "/api/workbench/parse", json={"conn_id": conn.conn_id, "text": "tables: [{}]\nunknown_root: true"}
        )
        assert invalid.status_code == 422
    registry.close_connection(conn.conn_id)


def test_deferred_child_still_validates_independent_generators(connection: Connection) -> None:
    from sqlseed_web.workbench_runtime import check_document
    from sqlseed_web.workbench_schema import inspect_connection

    config = document()
    config["tables"][0]["columns"][0]["params"] = {"nonexistent_parameter": 1}
    checked = check_document(connection, config, inspect_connection(connection)["schema_hash"])
    assert not checked["ok"], checked
    assert any(issue.get("table") == "children" and issue["severity"] == "error" for issue in checked["issues"])


def test_errors_remove_query_credentials() -> None:
    from sqlseed_web.workbench_runtime import public_error

    message = public_error(
        ValueError("postgresql://user:hidden@localhost/db?sslpassword=example-secret&access_token=another-secret")
    )
    assert "hidden" not in message
    assert "example-secret" not in message
    assert "another-secret" not in message


def test_check_catches_derived_null_and_unique_exhaustion(connection: Connection) -> None:
    from sqlseed_web.workbench_runtime import check_document
    from sqlseed_web.workbench_schema import inspect_connection

    with closing(sqlite3.connect(connection.target)) as db, db:
        db.execute("INSERT INTO parents(code) VALUES ('existing')")
    schema = inspect_connection(connection)
    config = document()
    config["tables"][0]["columns"][1]["expression"] = "None"
    null_result = check_document(connection, config, schema["schema_hash"])
    assert not null_result["ok"], null_result
    assert any(issue["code"] == "not_null_sample" for issue in null_result["issues"])
    config["tables"] = [
        {
            "name": "parents",
            "count": 10,
            "columns": [{"name": "code", "generator": "choice", "params": {"choices": ["same"]}}],
        }
    ]
    unique_result = check_document(connection, config, schema["schema_hash"])
    assert not unique_result["ok"], unique_result


def test_check_hash_changes_when_parent_values_change_at_same_row_count(connection: Connection) -> None:
    from sqlseed_web.workbench_runtime import check_document
    from sqlseed_web.workbench_schema import inspect_connection

    with closing(sqlite3.connect(connection.target)) as db, db:
        db.execute("INSERT INTO parents(id, code) VALUES (1, 'existing')")
    schema = inspect_connection(connection)
    before = check_document(connection, document(), schema["schema_hash"])
    with closing(sqlite3.connect(connection.target)) as db, db:
        db.execute("UPDATE parents SET id=2")
    after = check_document(connection, document(), schema["schema_hash"])
    assert before["ok"] and after["ok"]
    assert before["config_hash"] != after["config_hash"]


def test_sanitized_export_can_be_parsed_again(connection: Connection) -> None:
    from sqlseed_web.workbench_runtime import export_document, parse_document

    conn = Connection(
        "url", "postgresql://user:private@db.local/example?sslpassword=hidden", "base", "en_US", connection.orchestrator
    )
    exported = export_document(conn, document())
    parsed = parse_document(conn, exported["yaml"])
    assert parsed["tables"][0]["name"] == "children"
    assert "url" not in parsed


def test_store_run_atomically_requires_current_saved_revision(connection: Connection, tmp_path: Path) -> None:
    from sqlseed_web.workbench_runtime import normalize_document
    from sqlseed_web.workbench_schema import inspect_connection
    from sqlseed_web.workbench_store import RevisionConflict, WorkspaceStore

    store = WorkspaceStore(tmp_path / "revision.db")
    schema = inspect_connection(connection)
    payload = {
        "name": "plan",
        "target_key": schema["target_key"],
        "target_label": schema["target_label"],
        "schema_hash": schema["schema_hash"],
        "document": normalize_document(connection, document()),
        "view_state": {},
    }
    draft = store.save_draft(payload)
    store.save_draft(payload, draft_id=draft["id"], expected_revision=draft["revision"])
    with pytest.raises(RevisionConflict):
        store.create_run(
            {**payload, "draft_id": draft["id"], "revision": draft["revision"], "tables": []},
            require_current_draft=True,
        )
    assert store.list_runs() == []


def test_per_column_provider_cannot_silently_override_global_provider(connection: Connection) -> None:
    from sqlseed_web.workbench_runtime import check_document
    from sqlseed_web.workbench_schema import inspect_connection

    config = document()
    config["tables"][0]["columns"][0]["provider"] = "base"
    checked = check_document(connection, config, inspect_connection(connection)["schema_hash"])
    assert not checked["ok"]
    assert any(issue["code"] == "column_provider_not_supported" for issue in checked["issues"])


@pytest.mark.parametrize(("mapping_mode", "expected"), [("exact", 33), ("pattern", 44), ("explicit", 55)])
def test_saved_associations_and_custom_mappings_reach_core(
    connection: Connection, tmp_path: Path, mapping_mode: str, expected: int
) -> None:
    with closing(sqlite3.connect(connection.target)) as db, db:
        db.execute("CREATE TABLE associated (id INTEGER PRIMARY KEY, code_ref TEXT NOT NULL, marker INTEGER NOT NULL)")
    config = {
        "provider": "faker",
        "locale": "en_US",
        "optimize_pragma": False,
        "custom_column_mappings": {
            "exact": {"marker": {"generator": "integer", "params": {"min_value": 33, "max_value": 33}}}
        },
        "associations": [
            {
                "column_name": "code_ref",
                "source_table": "parents",
                "source_column": "code",
                "target_tables": ["associated"],
            }
        ],
        "tables": [
            {"name": "associated", "count": 4},
            {"name": "parents", "count": 3, "columns": [{"name": "code", "generator": "uuid"}]},
        ],
    }
    config["custom_column_mappings"]["pattern"] = [
        {"pattern": "^marker$", "generator": "integer", "params": {"min_value": 44, "max_value": 44}}
    ]
    if mapping_mode == "pattern":
        config["custom_column_mappings"]["exact"] = {}
    if mapping_mode == "explicit":
        config["tables"][0]["columns"] = [
            {"name": "marker", "generator": "integer", "params": {"min_value": 55, "max_value": 55}}
        ]
    run = run_plan(connection, config, tmp_path)
    assert run["status"] == "done", run
    with closing(sqlite3.connect(connection.target)) as db, db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM associated JOIN parents ON associated.code_ref = parents.code WHERE marker=?",
                (expected,),
            ).fetchone()[0]
            == 4
        )


def test_nullable_self_reference_is_supported(connection: Connection, tmp_path: Path) -> None:
    with closing(sqlite3.connect(connection.target)) as db, db:
        db.execute(
            "CREATE TABLE nodes (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES nodes(id), label TEXT NOT NULL)"
        )
    run = run_plan(
        connection,
        {
            "provider": "faker",
            "tables": [{"name": "nodes", "count": 10, "columns": [{"name": "label", "generator": "word"}]}],
        },
        tmp_path,
    )
    assert run["status"] == "done", run
    with closing(sqlite3.connect(connection.target)) as db, db:
        assert db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 10
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_source_check_explains_existing_parent_without_exposing_its_values(connection: Connection) -> None:
    from sqlseed_web.workbench_runtime import check_document
    from sqlseed_web.workbench_schema import inspect_connection

    with closing(sqlite3.connect(connection.target)) as db, db:
        db.execute("INSERT INTO parents(code) VALUES ('private-parent-value')")
    config = document()
    config["tables"] = config["tables"][:1]
    schema = inspect_connection(connection)
    result = check_document(connection, config, schema["schema_hash"])
    assert result["ok"], result
    source = result["sources"][0]
    assert source == {
        "table": "children",
        "column": "parent_id",
        "source_table": "parents",
        "source_columns": ["id"],
        "has_values": True,
        "row_count": 1,
        "selected": False,
        "nullable": False,
    }
    assert "private-parent-value" not in str(result["sources"])
