"""Explicit replacement plans use only temporary SQLite targets."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sqlseed_web.state import Connection, UIState
from sqlseed_web.workbench_runtime import WorkbenchError, check_document, normalize_document
from sqlseed_web.workbench_schema import inspect_connection
from sqlseed_web.workbench_store import WorkspaceStore


@pytest.fixture()
def target(tmp_path: Path) -> Iterator[tuple[UIState, Connection, WorkspaceStore]]:
    path = tmp_path / "target.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE parents(id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL);"
            "CREATE TABLE children(id INTEGER PRIMARY KEY AUTOINCREMENT, parent_id INTEGER NOT NULL REFERENCES parents(id));"
            "CREATE TABLE unrelated(id INTEGER PRIMARY KEY, content TEXT);"
            "INSERT INTO parents VALUES(40,'old');INSERT INTO children VALUES(60,40);"
            "INSERT INTO unrelated VALUES(7,'keep');"
        )
    registry = UIState()
    conn = registry.add_connection(str(path), provider="base")
    store = WorkspaceStore(tmp_path / "workspace.db")
    try:
        yield registry, conn, store
    finally:
        registry.close_connection(conn.conn_id)


def prepared(
    conn: Connection, store: WorkspaceStore, tables: list[dict[str, Any]] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    schema = inspect_connection(conn)
    document = normalize_document(
        conn,
        {
            "provider": "base",
            "locale": "en_US",
            "tables": tables
            or [
                {"name": "children", "count": 3, "batch_size": 2},
                {
                    "name": "parents",
                    "count": 4,
                    "batch_size": 2,
                    "columns": [{"name": "code", "generator": "template", "params": {"template": "new-{sequence}"}}],
                },
            ],
        },
    )
    draft = store.save_draft(
        {
            "name": "replace",
            "document": document,
            "schema_hash": schema["schema_hash"],
            "target_key": schema["target_key"],
            "target_label": schema["target_label"],
            "view_state": {},
        }
    )
    check = check_document(conn, document, schema["schema_hash"])
    assert check["ok"], check
    args = {
        "conn_id": conn.conn_id,
        "draft_id": draft["id"],
        "revision": draft["revision"],
        "schema_hash": schema["schema_hash"],
        "config_hash": check["config_hash"],
    }
    return args, draft


def wait_run(registry: UIState, store: WorkspaceStore, run: dict[str, Any]) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        current = store.get_run(run["id"])
        if current["status"] in {"done", "error"} and all(job.status != "running" for job in registry.recent_jobs()):
            return current
        time.sleep(0.01)
    pytest.fail("replacement worker did not finish")


def contents(conn: Connection) -> dict[str, Any]:
    with sqlite3.connect(conn.target) as db:
        return {
            name: db.execute(f'SELECT * FROM "{name}" ORDER BY 1').fetchall()
            for name in ["parents", "children", "unrelated", "sqlite_sequence"]
        }


def test_preflight_is_readonly_and_lists_reverse_dependency_clear_order(
    target: tuple[UIState, Connection, WorkspaceStore],
) -> None:
    from sqlseed_web.workbench_runtime import plan_execution

    registry, conn, store = target
    args, _ = prepared(conn, store)
    before = contents(conn)
    plan = plan_execution(
        **args, execution={"mode": "replace_selected", "reset_identity": True}, registry=registry, store=store
    )
    assert plan["ok"] and plan["atomic"] and plan["reset_identity_supported"]
    assert plan["delete_order"] == ["children", "parents"]
    assert plan["clear_tables"] == [{"name": "children", "row_count": 1}, {"name": "parents", "row_count": 1}]
    assert len(plan["plan_hash"]) == 64
    assert contents(conn) == before


@pytest.mark.parametrize("reset,first_parent,first_child", [(False, 41, 61), (True, 1, 1)])
def test_clear_and_reset_are_separate_and_foreign_keys_use_new_transaction_rows(
    target: tuple[UIState, Connection, WorkspaceStore], reset: bool, first_parent: int, first_child: int
) -> None:
    from sqlseed_web.workbench_runtime import plan_execution, start_run

    registry, conn, store = target
    args, _ = prepared(conn, store)
    execution = {"mode": "replace_selected", "reset_identity": reset}
    plan = plan_execution(**args, execution=execution, registry=registry, store=store)
    run = wait_run(
        registry,
        store,
        start_run(**args, execution=execution, plan_hash=plan["plan_hash"], registry=registry, store=store),
    )
    assert run["status"] == "done", run
    assert run["rows_inserted"] == 7
    assert run["execution"] == execution and run["plan_hash"] == plan["plan_hash"]
    rows = contents(conn)
    assert rows["parents"][0][0] == first_parent and len(rows["parents"]) == 4
    assert rows["children"][0][0] == first_child and len(rows["children"]) == 3
    assert {row[1] for row in rows["children"]} <= {row[0] for row in rows["parents"]}
    assert rows["unrelated"] == [(7, "keep")]
    with sqlite3.connect(conn.target) as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(ValueError, match="immutable"):
        store.update_run(run["id"], {"execution": {"mode": "append", "reset_identity": False}})


@pytest.mark.parametrize("action", ["NO ACTION", "CASCADE", "SET NULL"])
def test_external_incoming_fk_blocks_clearing_even_with_cascade(
    target: tuple[UIState, Connection, WorkspaceStore], action: str
) -> None:
    from sqlseed_web.workbench_runtime import plan_execution, start_run

    registry, conn, store = target
    with sqlite3.connect(conn.target) as db:
        db.executescript(
            f"DROP TABLE children; CREATE TABLE children(id INTEGER PRIMARY KEY AUTOINCREMENT, parent_id INTEGER REFERENCES parents(id) ON DELETE {action}); INSERT INTO children VALUES(60,40);"
        )
    args, _ = prepared(
        conn, store, [{"name": "parents", "count": 1, "columns": [{"name": "code", "generator": "uuid"}]}]
    )
    before = contents(conn)
    plan = plan_execution(**args, execution={"mode": "replace_selected"}, registry=registry, store=store)
    assert not plan["ok"]
    assert any(issue["code"] == "external_incoming_fk" and issue["table"] == "children" for issue in plan["issues"])
    with pytest.raises(WorkbenchError, match="引用|清空"):
        start_run(
            **args, execution={"mode": "replace_selected"}, plan_hash=plan["plan_hash"], registry=registry, store=store
        )
    assert contents(conn) == before


def test_late_generated_batch_failure_restores_every_original_row_and_sequence(
    target: tuple[UIState, Connection, WorkspaceStore],
) -> None:
    from sqlseed_web.workbench_runtime import plan_execution, start_run

    registry, conn, store = target
    with sqlite3.connect(conn.target) as db:
        db.executescript(
            "DELETE FROM children; DROP TABLE parents; CREATE TABLE parents(id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL CHECK(code <> 'new-4')); INSERT INTO parents VALUES(40,'old'); INSERT INTO children VALUES(60,40);"
        )
    args, _ = prepared(conn, store)
    before = contents(conn)
    execution = {"mode": "replace_selected", "reset_identity": True}
    plan = plan_execution(**args, execution=execution, registry=registry, store=store)
    assert plan["ok"], plan
    run = wait_run(
        registry,
        store,
        start_run(**args, execution=execution, plan_hash=plan["plan_hash"], registry=registry, store=store),
    )
    assert run["status"] == "error" and run["rows_inserted"] == 0
    assert run["result"]["rolled_back"] is True
    assert run["row_counts_exact"] is True
    assert all(table["rows_inserted"] == 0 for table in run["tables"])
    assert contents(conn) == before


def test_default_run_remains_append_and_replace_requires_current_plan_hash(
    target: tuple[UIState, Connection, WorkspaceStore],
) -> None:
    from sqlseed_web.workbench_runtime import plan_execution, start_run

    registry, conn, store = target
    args, _ = prepared(conn, store)
    plan = plan_execution(**args, registry=registry, store=store)
    assert plan["mode"] == "append" and not plan["atomic"] and plan["clear_tables"] == []
    with pytest.raises(WorkbenchError, match="计划|确认"):
        start_run(**args, execution={"mode": "replace_selected"}, plan_hash="old", registry=registry, store=store)
    run = wait_run(registry, store, start_run(**args, registry=registry, store=store))
    assert run["execution"] == {"mode": "append", "reset_identity": False}
    assert contents(conn)["parents"][0] == (40, "old")


def test_execution_options_reject_reset_during_append_and_unknown_flags(
    target: tuple[UIState, Connection, WorkspaceStore],
) -> None:
    from sqlseed_web.workbench_runtime import plan_execution

    registry, conn, store = target
    args, _ = prepared(conn, store)
    for execution in [
        {"mode": "append", "reset_identity": True},
        {"mode": "truncate"},
        {"mode": "append", "cascade": True},
    ]:
        with pytest.raises(WorkbenchError):
            plan_execution(**args, execution=execution, registry=registry, store=store)


def test_only_child_replacement_reads_unselected_parent_keys_without_modifying_parents(
    target: tuple[UIState, Connection, WorkspaceStore],
) -> None:
    from sqlseed_web.workbench_runtime import plan_execution, start_run

    registry, conn, store = target
    args, _ = prepared(conn, store, [{"name": "children", "count": 5, "batch_size": 2}])
    execution = {"mode": "replace_selected", "reset_identity": True}
    plan = plan_execution(**args, execution=execution, registry=registry, store=store)
    assert plan["ok"] and plan["delete_order"] == ["children"]
    run = wait_run(
        registry,
        store,
        start_run(**args, execution=execution, plan_hash=plan["plan_hash"], registry=registry, store=store),
    )
    rows = contents(conn)
    assert run["status"] == "done" and run["rows_inserted"] == 5
    assert rows["parents"] == [(40, "old")]
    assert rows["children"] == [(number, 40) for number in range(1, 6)]


@pytest.mark.parametrize("change", ["rows", "trigger"])
def test_worker_rechecks_after_writer_lock_and_before_any_delete(
    target: tuple[UIState, Connection, WorkspaceStore], monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

    from sqlseed_web.workbench_runtime import plan_execution, start_run

    registry, conn, store = target
    args, _ = prepared(conn, store)
    execution = {"mode": "replace_selected", "reset_identity": True}
    plan = plan_execution(**args, execution=execution, registry=registry, store=store)
    original = SQLAlchemyAdapter.transaction

    @contextmanager
    def concurrent_change(adapter: SQLAlchemyAdapter) -> Iterator[SQLAlchemyAdapter]:
        # Real second connection changes the target after request/worker checks,
        # immediately before the production writer takes BEGIN IMMEDIATE.
        with sqlite3.connect(conn.target) as db:
            if change == "rows":
                db.execute("INSERT INTO parents VALUES(42,'concurrent')")
            else:
                db.execute("CREATE TRIGGER outside_effect AFTER DELETE ON parents BEGIN DELETE FROM unrelated; END")
        with original(adapter):
            yield adapter

    monkeypatch.setattr(SQLAlchemyAdapter, "transaction", concurrent_change)
    run = wait_run(
        registry,
        store,
        start_run(**args, execution=execution, plan_hash=plan["plan_hash"], registry=registry, store=store),
    )
    assert run["status"] == "error" and run["rows_inserted"] == 0
    rows = contents(conn)
    assert rows["parents"] == ([(40, "old"), (42, "concurrent")] if change == "rows" else [(40, "old")])
    assert rows["children"] == [(60, 40)] and rows["unrelated"] == [(7, "keep")]


@pytest.mark.parametrize(
    "feature,code", [("trigger", "replacement_trigger_not_supported"), ("enrich", "replacement_enrich_not_supported")]
)
def test_replacement_blocks_unbounded_side_effects_and_removed_enrichment_sources(
    target: tuple[UIState, Connection, WorkspaceStore], feature: str, code: str
) -> None:
    from sqlseed_web.workbench_runtime import plan_execution

    registry, conn, store = target
    if feature == "trigger":
        with sqlite3.connect(conn.target) as db:
            db.execute("CREATE TRIGGER outside_effect AFTER INSERT ON children BEGIN DELETE FROM unrelated; END")
    args, _ = prepared(conn, store, [{"name": "children", "count": 2, "enrich": feature == "enrich"}])
    before = contents(conn)
    plan = plan_execution(**args, execution={"mode": "replace_selected"}, registry=registry, store=store)
    assert not plan["ok"] and any(issue["code"] == code for issue in plan["issues"])
    assert contents(conn) == before


def test_sqlite_nullable_self_reference_uses_new_ids_and_deferred_updates(
    target: tuple[UIState, Connection, WorkspaceStore],
) -> None:
    from sqlseed_web.workbench_runtime import plan_execution, start_run

    registry, conn, store = target
    with sqlite3.connect(conn.target) as db:
        db.executescript(
            "CREATE TABLE employees(id INTEGER PRIMARY KEY AUTOINCREMENT, manager_id INTEGER REFERENCES employees(id)); INSERT INTO employees VALUES(90,NULL); INSERT INTO employees VALUES(91,90);"
        )
    args, _ = prepared(conn, store, [{"name": "employees", "count": 8, "batch_size": 3}])
    execution = {"mode": "replace_selected", "reset_identity": True}
    plan = plan_execution(**args, execution=execution, registry=registry, store=store)
    assert plan["ok"], plan
    run = wait_run(
        registry,
        store,
        start_run(**args, execution=execution, plan_hash=plan["plan_hash"], registry=registry, store=store),
    )
    assert run["status"] == "done", run
    with sqlite3.connect(conn.target) as db:
        rows = db.execute("SELECT * FROM employees ORDER BY id").fetchall()
        assert [row[0] for row in rows] == list(range(1, 9))
        assert all(row[1] is None or 1 <= row[1] <= 8 for row in rows)
        assert any(row[1] is not None for row in rows)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_plain_integer_rowid_warning_and_postgresql_capability_gate(
    target: tuple[UIState, Connection, WorkspaceStore],
) -> None:
    from sqlseed_web.workbench_execution import build_execution_plan
    from sqlseed_web.workbench_runtime import bind_document, plan_execution

    registry, conn, store = target
    args, draft = prepared(conn, store, [{"name": "unrelated", "count": 2}])
    plan = plan_execution(**args, execution={"mode": "replace_selected"}, registry=registry, store=store)
    assert plan["ok"] and not plan["reset_identity_supported"]
    assert any(issue["code"] == "rowid_restarts_on_clear" for issue in plan["issues"])
    # Capability policy only: this does not claim PostgreSQL integration.
    schema = inspect_connection(conn) | {"dialect": "postgresql"}
    denied = build_execution_plan(
        conn,
        bind_document(conn, draft["document"]),
        schema,
        ["unrelated"],
        {"mode": "replace_selected", "reset_identity": False},
        args["config_hash"],
    )
    assert not denied["ok"] and not denied["atomic"]
    assert any(issue["code"] == "replacement_not_supported" for issue in denied["issues"])


def test_http_execution_plan_binding_and_run_options(
    target: tuple[UIState, Connection, WorkspaceStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlseed_web import workbench

    registry, conn, store = target
    args, _ = prepared(conn, store)
    monkeypatch.setattr(workbench, "state", registry)
    monkeypatch.setattr(workbench, "get_store", lambda: store)
    app = FastAPI()
    app.include_router(workbench.router)
    execution = {"mode": "replace_selected", "reset_identity": True}
    with TestClient(app) as client:
        assert client.post("/api/workbench/execution-plan", json=args | {"revision": 999}).status_code == 409
        assert (
            client.post("/api/workbench/execution-plan", json=args | {"execution": {"mode": "truncate"}}).status_code
            == 422
        )
        plan = client.post("/api/workbench/execution-plan", json=args | {"execution": execution})
        assert plan.status_code == 200 and plan.json()["ok"]
        assert client.post("/api/workbench/runs", json=args | {"execution": execution}).status_code == 409
        accepted = client.post(
            "/api/workbench/runs", json=args | {"execution": execution, "plan_hash": plan.json()["plan_hash"]}
        )
        assert accepted.status_code == 202
        run = wait_run(registry, store, accepted.json())
        assert run["status"] == "done" and run["execution"] == execution


def test_running_tables_never_report_uncommitted_batches_as_committed(
    target: tuple[UIState, Connection, WorkspaceStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlseed_web.workbench_runtime import plan_execution, start_run

    registry, conn, store = target
    args, _ = prepared(conn, store)
    execution = {"mode": "replace_selected", "reset_identity": True}
    plan = plan_execution(**args, execution=execution, registry=registry, store=store)
    before = contents(conn)
    update = store.update_run
    snapshots: list[dict[str, Any]] = []

    def observed_update(run_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        record = update(run_id, changes)
        if record["status"] == "running" and any(table["status"] == "running" for table in record["tables"]):
            assert record["rows_inserted"] == 0
            assert all(table["rows_inserted"] == 0 for table in record["tables"])
            assert contents(conn) == before
            snapshots.append(record)
        return record

    monkeypatch.setattr(store, "update_run", observed_update)
    run = wait_run(
        registry,
        store,
        start_run(**args, execution=execution, plan_hash=plan["plan_hash"], registry=registry, store=store),
    )
    assert run["status"] == "done" and run["rows_inserted"] == 7
    assert run["result"] == {"atomic": True, "committed": True, "rolled_back": False}
    assert len(snapshots) == 2
    assert all(table["status"] == "running" for table in snapshots[-1]["tables"])


def test_existing_self_reference_restrict_blocks_before_delete(
    target: tuple[UIState, Connection, WorkspaceStore],
) -> None:
    from sqlseed_web.workbench_runtime import plan_execution

    registry, conn, store = target
    with sqlite3.connect(conn.target) as db:
        db.executescript(
            "CREATE TABLE employees(id INTEGER PRIMARY KEY AUTOINCREMENT, manager_id INTEGER REFERENCES employees(id) ON DELETE RESTRICT); INSERT INTO employees VALUES(90,NULL); INSERT INTO employees VALUES(91,90);"
        )
    args, _ = prepared(conn, store, [{"name": "employees", "count": 8}])
    plan = plan_execution(**args, execution={"mode": "replace_selected"}, registry=registry, store=store)
    assert not plan["ok"]
    assert any(issue["code"] == "self_reference_delete_restrict" for issue in plan["issues"])
