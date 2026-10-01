"""Real SQLite/API evidence behind the frontend's complex graph fixture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.assertions import assert_empty
from tests.sqlite_helpers import sqlite_connection

from sqlseed_web import workbench
from sqlseed_web.state import UIState

from .complex_graph_fixture import create_database, export_checks, export_schema, graph_snapshot


def test_business_graph_snapshot_matches_the_real_http_schema_and_checks(tmp_path: Path) -> None:
    path = tmp_path / "business.sqlite3"
    create_database(path, seed_cycles=False)
    schema = export_schema(path)
    checks = export_checks(path, schema)
    expected = json.loads(Path(__file__).with_name("complex_business_graph.json").read_text(encoding="utf-8"))
    assert graph_snapshot(schema, checks) == expected
    assert len(schema["nodes"]) == 26
    assert len(schema["edges"]) == 55
    assert checks["fulfillment"]["ok"]
    assert checks["composite"]["ok"]
    issue = next(issue for issue in checks["cycles"]["issues"] if issue["code"] == "cross_table_cycle")
    assert issue["code"] == "cross_table_cycle"
    assert issue["tables"] == ["departments", "employees"]
    assert len(issue["edge_ids"]) == 2
    assert issue["references"] == [
        {"table": "departments", "columns": ["manager_id"], "source_table": "employees", "source_columns": ["id"]},
        {"table": "employees", "columns": ["department_id"], "source_table": "departments", "source_columns": ["id"]},
    ]
    assert "suppliers" not in issue["tables"], "A downstream table is blocked, but is not itself in the cycle"
    with sqlite_connection(path) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT count(*) FROM sales_orders").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM stock_movements").fetchone() == (2,)
    with pytest.raises(FileExistsError):
        create_database(path, seed_cycles=False)


def test_missing_composite_source_identifies_the_exact_target_column_group(tmp_path: Path) -> None:
    path = tmp_path / "empty-bins.sqlite3"
    create_database(path, seed_cycles=False)
    with sqlite_connection(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript("""
            DELETE FROM stock_movements;
            DELETE FROM shipment_items;
            DELETE FROM receipt_items;
            DELETE FROM inventory;
            DELETE FROM warehouse_bins;
        """)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    schema = export_schema(path)
    result = export_checks(path, schema, {"composite": ["inventory"]})["composite"]
    assert not result["ok"]
    issue = next(issue for issue in result["issues"] if issue["code"] == "missing_parent_source")
    assert issue["table"] == "inventory"
    assert issue["source_table"] == "warehouse_bins"
    assert issue["column"] == "warehouse_id,bin_code"
    assert issue["columns"] == ["warehouse_id", "bin_code"]


@pytest.mark.parametrize("endpoint", ["check", "preview"])
def test_selecting_all_tables_retains_the_exact_cycle_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    path = tmp_path / "all-selected.sqlite3"
    create_database(path, seed_cycles=False)
    schema = export_schema(path)
    selected = [table["name"] for table in schema["tables"]]
    assert len(selected) == 26
    with sqlite_connection(path) as db:
        before = list(db.iterdump())
    registry = UIState()
    connection = registry.add_connection(str(path), provider="base")
    monkeypatch.setattr(workbench, "state", registry)
    app = FastAPI()
    app.include_router(workbench.router)
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/workbench/{endpoint}",
                json={
                    "conn_id": connection.conn_id,
                    "schema_hash": schema["schema_hash"],
                    "document": {
                        "provider": "base",
                        "tables": [{"name": name, "count": 3} for name in selected],
                    },
                },
            )
            response.raise_for_status()
            result = response.json()
        assert result["ok"] is False
        errors = [issue for issue in result["issues"] if issue["severity"] == "error"]
        assert len(errors) == 1
        issue = errors[0]
        assert issue["severity"] == "error"
        assert issue["code"] == "cross_table_cycle"
        assert issue["tables"] == ["departments", "employees"]
        assert issue["references"] == [
            {"table": "departments", "columns": ["manager_id"], "source_table": "employees", "source_columns": ["id"]},
            {
                "table": "employees",
                "columns": ["department_id"],
                "source_table": "departments",
                "source_columns": ["id"],
            },
        ]
        assert len(issue["edge_ids"]) == 2
        assert {(edge["source"], edge["target"]) for edge in schema["edges"] if edge["id"] in issue["edge_ids"]} == {
            ("departments", "employees"),
            ("employees", "departments"),
        }
        assert_empty(result["samples"], dict)
    finally:
        registry.close_connection(connection.conn_id)
    with sqlite_connection(path) as db:
        assert list(db.iterdump()) == before
        assert_empty(db.execute("PRAGMA foreign_key_check").fetchall(), list)


def test_multiple_cycles_report_only_internal_edges_not_bridges_or_descendants(tmp_path: Path) -> None:
    path = tmp_path / "two-cycles.sqlite3"
    create_database(path, seed_cycles=False)
    with sqlite_connection(path) as connection:
        connection.execute("ALTER TABLE returns ADD COLUMN refund_id INTEGER REFERENCES refunds(id)")
        connection.execute("ALTER TABLE returns ADD COLUMN approved_by INTEGER REFERENCES employees(id)")
        connection.execute("DELETE FROM refunds")
    schema = export_schema(path)
    selected = ["departments", "employees", "suppliers", "returns", "refunds", "return_items"]
    result = export_checks(path, schema, {"two": selected})["two"]
    issue = next(issue for issue in result["issues"] if issue["code"] == "cross_table_cycle")
    assert issue["tables"] == ["departments", "employees", "returns", "refunds"]
    pairs = {(edge["source"], edge["target"]) for edge in schema["edges"] if edge["id"] in issue["edge_ids"]}
    assert pairs == {
        ("departments", "employees"),
        ("employees", "departments"),
        ("returns", "refunds"),
        ("refunds", "returns"),
    }
    assert {(reference["source_table"], reference["table"]) for reference in issue["references"]} == pairs


def test_retaining_cycle_and_upstream_removes_only_the_cycle_not_remaining_clear_checks(tmp_path: Path) -> None:
    from sqlseed_web.workbench_execution import build_execution_plan
    from sqlseed_web.workbench_runtime import bind_document, check_document

    path = tmp_path / "cycle-recovery.sqlite3"
    create_database(path, seed_cycles=False)
    schema = export_schema(path)
    selected = ["addresses", "departments", "employees", "tenants"]
    checks = export_checks(path, schema, {"original": selected, "retained": ["addresses"]})
    assert not checks["original"]["ok"]
    cycle = next(issue for issue in checks["original"]["issues"] if issue["code"] == "cross_table_cycle")
    assert cycle["tables"] == ["departments", "employees"]
    assert checks["retained"]["ok"]
    registry = UIState()
    connection = registry.add_connection(str(path), provider="base")
    try:
        document = {"provider": "base", "tables": [{"name": "addresses", "count": 3}]}
        checked = check_document(connection, document, schema["schema_hash"])
        plan = build_execution_plan(
            connection,
            bind_document(connection, document),
            schema,
            checked["order"],
            {"mode": "replace_selected", "reset_identity": False},
            checked["config_hash"],
        )
        assert not plan["ok"], "Removing the cycle cannot promise that the remaining clear scope is valid"
        assert {issue["table"] for issue in plan["issues"] if issue["code"] == "external_incoming_fk"} == {
            "customers",
            "sales_orders",
            "warehouses",
        }
    finally:
        registry.close_connection(connection.conn_id)
    with sqlite_connection(path) as db:
        assert db.execute("SELECT manager_id FROM departments").fetchall() == []
        assert db.execute("SELECT department_id FROM employees").fetchall() == []
        assert db.execute("SELECT count(*) FROM addresses").fetchone() == (1,)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
