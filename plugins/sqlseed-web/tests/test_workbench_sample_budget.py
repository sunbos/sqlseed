"""Bounded and cancellable workbench checks use real SQLite without writes."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from tests.assertions import assert_empty
from tests.sqlite_helpers import sqlite_connection

from sqlseed_web.state import Connection, UIState
from sqlseed_web.workbench_runtime import check_document
from sqlseed_web.workbench_schema import inspect_connection


@pytest.fixture(name="conn")
def fixture_conn(tmp_path: Path) -> Iterator[Connection]:
    path = tmp_path / "samples.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE items(code TEXT NOT NULL UNIQUE);"
            "CREATE TABLE later(value INTEGER NOT NULL);"
            "CREATE TABLE ranges(a INTEGER NOT NULL, b INTEGER NOT NULL, CHECK(a < b));"
            "CREATE TABLE children(parent_code TEXT NOT NULL REFERENCES items(code), code TEXT NOT NULL UNIQUE);"
        )
    state = UIState()
    connection = state.add_connection(str(path), provider="base")
    yield connection
    state.close_connection(connection.conn_id)


def document(table: str = "items") -> dict[str, Any]:
    # A fixed template reaches sample validation. A one-character string
    # alphabet is now correctly rejected by UNIQUE capacity preflight.
    columns = [{"name": "code", "generator": "template", "params": {"template": "PPPPPPPPPPPPP"}}]
    if table == "ranges":
        columns = [
            {"name": name, "generator": "integer", "params": {"min_value": 1, "max_value": 1}} for name in ("a", "b")
        ]
    return {"provider": "base", "tables": [{"name": table, "count": 3, "columns": columns}]}


@pytest.mark.parametrize("table", ["items", "ranges", "children"])
def test_invalid_samples_stop_at_budget_without_inserting(conn: Connection, table: str) -> None:
    config = document(table)
    if table == "children":
        config["tables"].insert(0, {"name": "items", "count": 1, "columns": [{"name": "code", "generator": "uuid"}]})
    result = check_document(conn, config, inspect_connection(conn)["schema_hash"], sample_max_attempts=12, preview=True)
    assert not result["ok"], result
    issue = next(issue for issue in result["issues"] if issue["code"] == "generation_invalid")
    assert issue["table"] == table
    assert "样例校验" in issue["message"]
    assert "12 次尝试上限" in issue["message"]
    assert issue["column"] == ("b" if table == "ranges" else "code")
    assert issue["generator"] == ("integer" if table == "ranges" else "template")
    assert issue["attempt_limit"] == 12
    assert "PPPPPPPPPPPPP" not in issue["message"]
    for name in ("items", "ranges", "children"):
        assert conn.orchestrator.get_row_count(name) == 0


def test_impossible_string_capacity_is_rejected_without_writing(conn: Connection) -> None:
    config = document()
    config["tables"][0]["columns"] = [
        {"name": "code", "generator": "string", "params": {"min_length": 13, "max_length": 13, "charset": "P"}}
    ]
    result = check_document(conn, config, inspect_connection(conn)["schema_hash"], sample_max_attempts=12, preview=True)
    assert result["ok"] is False
    assert_empty(result["samples"], dict)
    issue = next(issue for issue in result["issues"] if issue["code"] == "generation_invalid")
    assert "cannot provide 3 UNIQUE strings" in issue["message"]
    assert "12 次尝试上限" not in issue["message"]
    assert conn.orchestrator.get_row_count("items") == 0


def test_cancel_exception_escapes_without_validating_later_tables(conn: Connection) -> None:
    config = document()
    config["tables"].append({"name": "later", "count": 3})
    reason = HTTPException(499, detail={"code": "ai_cancelled", "message": "分析已取消。"})
    calls = 0

    def cancel_check() -> None:
        nonlocal calls
        calls += 1
        if calls == 12:
            raise reason

    schema_hash = inspect_connection(conn)["schema_hash"]
    with pytest.raises(HTTPException) as caught:
        check_document(conn, config, schema_hash, cancel_check=cancel_check)
    assert caught.value is reason
    assert calls == 12
    assert conn.orchestrator.get_row_count("items") == conn.orchestrator.get_row_count("later") == 0


def test_regular_sample_check_still_succeeds(conn: Connection) -> None:
    config = {"provider": "base", "tables": [{"name": "later", "count": 3}]}
    checked = check_document(conn, config, inspect_connection(conn)["schema_hash"], preview=True)
    assert checked["ok"], checked
    assert len(checked["samples"]["later"]) == 3
    assert conn.orchestrator.get_row_count("later") == 0
