"""Real SQLite/API evidence behind the frontend's complex graph fixture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.sqlite_helpers import sqlite_connection

from .complex_graph_fixture import create_database, export_checks, export_schema, graph_snapshot


def test_business_graph_snapshot_matches_the_real_http_schema_and_checks(tmp_path: Path) -> None:
    path = tmp_path / "business.sqlite3"
    create_database(path)
    schema = export_schema(path)
    checks = export_checks(path, schema)
    expected = json.loads(Path(__file__).with_name("complex_business_graph.json").read_text(encoding="utf-8"))
    assert graph_snapshot(schema, checks) == expected
    assert len(schema["nodes"]) == 26
    assert len(schema["edges"]) == 55
    assert checks["fulfillment"]["ok"]
    assert checks["composite"]["ok"]
    issue = checks["cycles"]["issues"][0]
    assert issue["code"] == "cross_table_cycle"
    assert issue["tables"] == ["departments", "employees"]
    assert len(issue["edge_ids"]) == 2
    assert "suppliers" not in issue["tables"], "A downstream table is blocked, but is not itself in the cycle"
    with sqlite_connection(path) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT count(*) FROM sales_orders").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM stock_movements").fetchone() == (2,)
    with pytest.raises(FileExistsError):
        create_database(path)


def test_missing_composite_source_identifies_the_exact_target_column_group(tmp_path: Path) -> None:
    path = tmp_path / "empty-bins.sqlite3"
    create_database(path)
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


def test_multiple_cycles_report_only_internal_edges_not_bridges_or_descendants(tmp_path: Path) -> None:
    path = tmp_path / "two-cycles.sqlite3"
    create_database(path)
    with sqlite_connection(path) as connection:
        connection.execute("ALTER TABLE returns ADD COLUMN refund_id INTEGER REFERENCES refunds(id)")
        connection.execute("ALTER TABLE returns ADD COLUMN approved_by INTEGER REFERENCES employees(id)")
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
