"""Existing-key cycles append atomically without inventing or backfilling keys."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlseed.config.models import GeneratorConfig
from tests.sqlite_helpers import sqlite_connection

from sqlseed_web.state import Connection, UIState
from sqlseed_web.workbench_cycles import ExistingSourceOrchestrator
from sqlseed_web.workbench_execution import build_execution_plan
from sqlseed_web.workbench_runtime import bind_document, check_document
from sqlseed_web.workbench_schema import inspect_connection

from .complex_graph_fixture import create_database
from .test_workbench_execution import prepared
from .test_workbench_runtime import run_plan


def _document(names: list[str], count: int = 3) -> dict:
    return {
        "provider": "base",
        "tables": [{"name": name, "count": count, "seed": 31, "batch_size": 2} for name in names],
    }


@pytest.fixture(name="all_table_configuration")
def fixture_all_table_configuration(tmp_path: Path) -> Iterator[tuple[Connection, Path, dict, dict]]:
    path = tmp_path / "commerce.db"
    create_database(path)
    registry = UIState()
    conn = registry.add_connection(str(path), provider="base")
    try:
        schema = inspect_connection(conn)
        document = _document([table["name"] for table in schema["tables"]])
        yield conn, path, schema, document
    finally:
        registry.close_connection(conn.conn_id)


def test_all_26_tables_append_with_existing_cycle_keys_and_valid_foreign_keys(
    all_table_configuration: tuple[Connection, Path, dict, dict], tmp_path: Path
) -> None:
    conn, path, schema, document = all_table_configuration
    checked = check_document(conn, document, schema["schema_hash"], preview=True)
    assert checked["ok"], checked["issues"]
    assert len(checked["order"]) == 26
    assert len(checked["samples"]) == 26
    assert {row["manager_id"] for row in checked["samples"]["departments"]} <= {None, 1}
    assert {row["department_id"] for row in checked["samples"]["employees"]} <= {None, 1}
    assert conn.orchestrator.get_row_count("departments") == 1
    plan = build_execution_plan(
        conn,
        bind_document(conn, document),
        schema,
        checked["order"],
        {"mode": "append", "reset_identity": False},
        checked["config_hash"],
        atomic_append=bool(checked["existing_cycle_sources"]),
    )
    assert plan["ok"]
    assert plan["atomic"]
    run = run_plan(conn, document, tmp_path, timeout=60)
    assert run["status"] == "done", run
    assert run["rows_inserted"] == 78
    assert run["result"] == {"atomic": True, "committed": True, "rolled_back": False}
    with sqlite_connection(path) as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT count(*) FROM departments").fetchone() == (4,)
        assert db.execute("SELECT DISTINCT manager_id FROM departments WHERE id>1").fetchall() == [(1,)]
        assert db.execute("SELECT DISTINCT department_id FROM employees WHERE id>1").fetchall() == [(1,)]
        assert db.execute("SELECT count(*) FROM stock_movements").fetchone() == (5,)


def test_seeded_cycle_append_does_not_authorize_clearing_or_identity_reset(
    all_table_configuration: tuple[Connection, Path, dict, dict],
) -> None:
    conn, _path, schema, document = all_table_configuration
    checked = check_document(conn, document, schema["schema_hash"])
    assert checked["ok"], checked["issues"]
    for reset in (False, True):
        plan = build_execution_plan(
            conn,
            bind_document(conn, document),
            schema,
            checked["order"],
            {"mode": "replace_selected", "reset_identity": reset},
            checked["config_hash"],
        )
        assert not plan["ok"]
        assert any(issue["code"] == "replacement_cycle_not_supported" for issue in plan["issues"])
    assert conn.orchestrator.get_row_count("departments") == 1


@pytest.mark.parametrize(
    "links,issue_code",
    [
        ([("catalog", "orders")], None),
        ([("catalog", "orders"), ("orders", "catalog")], "replacement_cycle_not_supported"),
        ([("outside", "catalog"), ("catalog", "orders")], None),
        ([("catalog", "orders"), ("catalog", "outside")], "external_incoming_association"),
        ([("catalog", "catalog"), ("catalog", "orders")], None),
    ],
    ids=["acyclic", "cycle", "external-source", "external-target", "self-source"],
)
def test_replacement_plan_checks_configured_associations_within_the_selected_scope(
    tmp_path: Path, links: list[tuple[str, str]], issue_code: str | None
) -> None:
    path = tmp_path / "associations.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE catalog(id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL);"
            "CREATE TABLE orders(id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL);"
            "CREATE TABLE outside(id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL);"
            "INSERT INTO catalog VALUES(10,'catalog-original');"
            "INSERT INTO orders VALUES(20,'orders-original');"
            "INSERT INTO outside VALUES(30,'outside-original');"
        )
        before = list(db.iterdump())
    registry = UIState()
    conn = registry.add_connection(str(path), provider="base")
    try:
        schema = inspect_connection(conn)
        document = _document(["catalog", "orders"])
        document["associations"] = [
            {"column_name": "code", "source_table": source, "target_tables": [target]} for source, target in links
        ]
        checked = check_document(conn, document, schema["schema_hash"], preview=True)
        if issue_code == "replacement_cycle_not_supported":
            assert not checked["ok"]
            assert any(issue["code"] == "cross_table_cycle" for issue in checked["issues"])
            assert checked["existing_cycle_sources"] == []
        plan = build_execution_plan(
            conn,
            bind_document(conn, document),
            schema,
            ["catalog", "orders"],
            {"mode": "replace_selected", "reset_identity": True},
            checked["config_hash"],
        )
        assert plan["ok"] is (issue_code is None)
        assert [issue["code"] for issue in plan["issues"]] == ([issue_code] if issue_code else [])
    finally:
        registry.close_connection(conn.conn_id)
    with sqlite_connection(path) as db:
        assert list(db.iterdump()) == before


def test_cycle_append_rolls_back_every_batch_and_retains_original_records(tmp_path: Path) -> None:
    path = tmp_path / "rollback.db"
    create_database(path)
    with sqlite_connection(path) as db:
        db.execute("CREATE TRIGGER reject_employee BEFORE INSERT ON employees BEGIN SELECT RAISE(ABORT, 'reject'); END")
        before = list(db.iterdump())
    registry = UIState()
    conn = registry.add_connection(str(path), provider="base")
    try:
        run = run_plan(conn, _document(["departments", "employees"]), tmp_path)
        assert run["status"] == "error"
        assert run["rows_inserted"] == 0
        assert run["row_counts_exact"] is True
        assert run["result"] == {"atomic": True, "committed": False, "rolled_back": True}
        assert all(table["rows_inserted"] == 0 for table in run["tables"])
    finally:
        registry.close_connection(conn.conn_id)
    with sqlite_connection(path) as db:
        assert list(db.iterdump()) == before
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("required", [False, True])
def test_empty_cycles_stay_unsupported_without_null_rule_changes(tmp_path: Path, required: bool) -> None:
    path = tmp_path / "empty.db"
    constraint = "NOT NULL" if required else ""
    with sqlite_connection(path) as db:
        db.executescript(
            f"CREATE TABLE a (id INTEGER PRIMARY KEY, b_id INTEGER {constraint} REFERENCES b(id));"
            f"CREATE TABLE b (id INTEGER PRIMARY KEY, a_id INTEGER {constraint} REFERENCES a(id));"
        )
    registry = UIState()
    conn = registry.add_connection(str(path), provider="base")
    try:
        schema = inspect_connection(conn)
        checked = check_document(conn, _document(["a", "b"]), schema["schema_hash"], preview=True)
        assert not checked["ok"]
        assert any(issue["code"] == "cross_table_cycle" for issue in checked["issues"])
        assert conn.orchestrator.get_row_count("a") == 0
        assert conn.orchestrator.get_row_count("b") == 0
    finally:
        registry.close_connection(conn.conn_id)


def test_existing_keys_do_not_bypass_unique_foreign_key_capacity(tmp_path: Path) -> None:
    path = tmp_path / "unique.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE a (id INTEGER PRIMARY KEY, b_id INTEGER UNIQUE REFERENCES b(id));"
            "CREATE TABLE b (id INTEGER PRIMARY KEY, a_id INTEGER REFERENCES a(id));"
            "INSERT INTO a VALUES(1, NULL); INSERT INTO b VALUES(1, 1); UPDATE a SET b_id=1;"
        )
    registry = UIState()
    conn = registry.add_connection(str(path), provider="base")
    try:
        schema = inspect_connection(conn)
        checked = check_document(conn, _document(["a", "b"]), schema["schema_hash"], sample_max_attempts=50)
        assert not checked["ok"]
        assert any(issue["severity"] == "error" for issue in checked["issues"])
        assert conn.orchestrator.get_row_count("a") == 1
    finally:
        registry.close_connection(conn.conn_id)


def test_source_changes_after_queuing_reject_before_any_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlseed_web import workbench_runtime
    from sqlseed_web.workbench_store import WorkspaceStore

    path = tmp_path / "changed-source.db"
    create_database(path)
    registry = UIState()
    conn = registry.add_connection(str(path), provider="base")
    store = WorkspaceStore(tmp_path / "history.db")
    scheduled: list[dict] = []
    monkeypatch.setattr(workbench_runtime, "start_background", lambda **kwargs: scheduled.append(kwargs))
    try:
        args, _ = prepared(conn, store, _document(["departments", "employees"])["tables"])
        plan = workbench_runtime.plan_execution(**args, registry=registry, store=store)
        assert plan["ok"]
        assert plan["atomic"]
        run = workbench_runtime.start_run(**args, registry=registry, store=store)
        assert run["atomic_append"] is True
        with sqlite_connection(path) as db:
            db.execute("INSERT INTO employees VALUES(2, 1, 1, NULL, 'external insertion')")
        task = scheduled[0]
        task["target"](*task["args"], **task["kwargs"])
        result = store.get_run(run["id"])
        assert result["status"] == "error"
        assert result["rows_inserted"] == 0
        assert all(table["status"] == "not_run" for table in result["tables"])
        assert conn.orchestrator.get_row_count("departments") == 1
        assert conn.orchestrator.get_row_count("employees") == 2
        assert all(job.status != "running" for job in registry.recent_jobs())
    finally:
        registry.close_connection(conn.conn_id)


@pytest.mark.parametrize("overlapping", [False, True])
def test_cycle_pinning_never_overrides_a_different_configured_or_physical_source(
    tmp_path: Path, overlapping: bool
) -> None:
    path = tmp_path / "conflicting-source.db"
    extra = ", FOREIGN KEY(b_id) REFERENCES c(id)" if overlapping else ""
    with sqlite_connection(path) as db:
        db.executescript(
            f"CREATE TABLE a(id INTEGER PRIMARY KEY, b_id INTEGER REFERENCES b(id){extra});"
            "CREATE TABLE b(id INTEGER PRIMARY KEY, a_id INTEGER REFERENCES a(id));"
            "CREATE TABLE c(id INTEGER PRIMARY KEY); INSERT INTO c VALUES(1),(999);"
            "INSERT INTO a VALUES(1,NULL); INSERT INTO b VALUES(1,1); UPDATE a SET b_id=1;"
        )
    registry = UIState()
    conn = registry.add_connection(str(path), provider="base")
    try:
        schema = inspect_connection(conn)
        document = _document(["a", "b"])
        if not overlapping:
            document["tables"][0]["columns"] = [
                {"name": "b_id", "generator": "foreign_key", "params": {"ref_table": "c", "ref_column": "id"}}
            ]
        checked = check_document(conn, document, schema["schema_hash"], preview=True)
        assert not checked["ok"]
        expected = "cross_table_cycle" if overlapping else "generation_invalid"
        assert any(issue["code"] == expected for issue in checked["issues"])
        assert conn.orchestrator.get_row_count("a") == 1
        assert conn.orchestrator.get_row_count("b") == 1
    finally:
        registry.close_connection(conn.conn_id)


def test_cycle_policy_preserves_keyword_specs_fresh_foreign_keys_and_associations(tmp_path: Path) -> None:
    path = tmp_path / "relation-policy.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE a(id INTEGER PRIMARY KEY, b_id INTEGER REFERENCES b(id));"
            "CREATE TABLE b(id INTEGER PRIMARY KEY, a_id INTEGER REFERENCES a(id));"
            "CREATE TABLE child(id INTEGER PRIMARY KEY, a_id INTEGER REFERENCES a(id));"
            "CREATE TABLE regions(id INTEGER PRIMARY KEY, code TEXT NOT NULL);"
            "CREATE TABLE sales(id INTEGER PRIMARY KEY, code_ref TEXT NOT NULL);"
            "INSERT INTO a VALUES(1,NULL); INSERT INTO b VALUES(1,1); UPDATE a SET b_id=1;"
            "INSERT INTO regions VALUES(1,'existing');"
        )
    config = GeneratorConfig.model_validate(
        {
            "db_path": str(path),
            "provider": "base",
            "associations": [
                {
                    "column_name": "code_ref",
                    "source_table": "regions",
                    "source_column": "code",
                    "target_tables": ["sales"],
                }
            ],
        }
    )
    with ExistingSourceOrchestrator.for_config(config) as orch, orch.database_adapter.transaction():
        orch.pin_cycle_sources(
            [
                {"table": "a", "column": "b_id", "source_table": "b", "source_columns": ["id"]},
                {"table": "b", "column": "a_id", "source_table": "a", "source_columns": ["id"]},
            ]
        )
        specs, _, _, _ = orch._resolve_specs(
            table_name="a", count=3, columns=None, column_configs=None, enrich=False, clear_before=False
        )
        assert specs["b_id"].params["_ref_values"] == [1]
        orch.fill_table("a", count=3, seed=1, skip_ai=True)
        orch.fill_table("b", count=3, seed=2, skip_ai=True)
        child_specs, _, _, _ = orch._resolve_specs(
            table_name="child", count=4, columns=None, column_configs=None, enrich=False
        )
        assert set(child_specs["a_id"].params["_ref_values"]) == {1, 2, 3, 4}
        orch.fill_table(
            "child",
            count=4,
            columns={
                "a_id": {
                    "generator": "foreign_key",
                    "params": {"ref_table": "a", "ref_column": "id", "strategy": "coverage"},
                }
            },
            seed=3,
            skip_ai=True,
        )
        association_specs, _, _, _ = orch._resolve_specs(
            table_name="sales", count=3, columns=None, column_configs=None, enrich=False
        )
        assert association_specs["code_ref"].params["_ref_values"] == ["existing"]
        orch.fill_table("sales", count=3, seed=4, skip_ai=True)
    with sqlite_connection(path) as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT id,b_id FROM a WHERE id=1").fetchall() == [(1, 1)]
        assert db.execute("SELECT b_id FROM a WHERE id>1").fetchall() == [(1,), (1,), (1,)]
        assert db.execute("SELECT a_id FROM b WHERE id>1").fetchall() == [(1,), (1,), (1,)]
        assert db.execute("SELECT DISTINCT a_id FROM child ORDER BY a_id").fetchall() == [(1,), (2,), (3,), (4,)]
        assert db.execute("SELECT code_ref FROM sales").fetchall() == [("existing",)] * 3


def test_direct_internal_session_rejects_pinning_without_the_configured_policy(tmp_path: Path) -> None:
    path = tmp_path / "unconfigured-policy.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE original(id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO original VALUES(1)")
    with (
        ExistingSourceOrchestrator(str(path), provider_name="base") as orch,
        pytest.raises(TypeError, match="require for_config"),
    ):
        orch.pin_cycle_sources([])
    with sqlite_connection(path) as db:
        assert db.execute("SELECT id FROM original").fetchall() == [(1,)]
