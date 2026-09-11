"""Invalid supplied YAML must not fall back to unconfigured writes."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest
import yaml
from mcp_server_sqlseed.server import sqlseed_execute_fill

if TYPE_CHECKING:
    from pathlib import Path


def create_database(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            "CREATE TABLE users (value INTEGER NOT NULL);"
            "CREATE TABLE orders (value INTEGER NOT NULL);"
            "INSERT INTO users VALUES (91); INSERT INTO orders VALUES (92);"
        )


def assert_unchanged(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT value FROM users").fetchall() == [(91,)]
        assert connection.execute("SELECT value FROM orders").fetchall() == [(92,)]


def test_yaml_without_target_table_is_rejected_before_writes(tmp_path: Path) -> None:
    database = tmp_path / "wrong-target.db"
    create_database(database)
    document = yaml.safe_dump({"db_path": str(database), "tables": [{"name": "orders", "count": 1}]})

    result = sqlseed_execute_fill(str(database), "users", count=2, yaml_config=document)

    assert "error" in result, result
    assert "users" in result["error"]
    assert "configuration" in result["error"].lower()
    assert_unchanged(database)


@pytest.mark.parametrize("document", ["[]", "null", "42", "true", "", "   "])
def test_non_mapping_yaml_returns_regular_error_and_preserves_rows(tmp_path: Path, document: str) -> None:
    database = tmp_path / "invalid.db"
    create_database(database)

    result = sqlseed_execute_fill(str(database), "users", count=2, yaml_config=document)

    assert "error" in result, result
    assert "mapping" in result["error"].lower()
    assert_unchanged(database)


@pytest.mark.parametrize("include_valid_config", [False, True])
def test_integer_yaml_key_returns_error_before_writes(tmp_path: Path, include_valid_config: bool) -> None:
    database = tmp_path / "integer-key.db"
    create_database(database)
    data = {1: "invalid-key"}
    if include_valid_config:
        data.update({"db_path": str(database), "tables": [{"name": "users", "count": 2, "clear_before": True}]})

    result = sqlseed_execute_fill(str(database), "users", count=2, yaml_config=yaml.safe_dump(data))

    assert "error" in result, result
    assert "keys" in result["error"].lower()
    assert "string" in result["error"].lower()
    assert_unchanged(database)


def test_valid_yaml_keeps_tool_target_count_and_matching_column_rules(tmp_path: Path) -> None:
    database = tmp_path / "valid.db"
    create_database(database)
    document = yaml.safe_dump(
        {
            "db_path": str(database),
            "provider": "base",
            "tables": [
                {"name": "orders", "count": 7, "clear_before": True},
                {
                    "name": "users",
                    "count": 99,
                    "columns": [
                        {"name": "value", "generator": "integer", "params": {"min_value": 17, "max_value": 17}},
                    ],
                },
            ],
        }
    )

    result = sqlseed_execute_fill(str(database), "users", count=2, yaml_config=document)

    assert result["count"] == 2
    assert result["errors"] == []
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT value FROM users ORDER BY rowid").fetchall() == [(91,), (17,), (17,)]
        assert connection.execute("SELECT value FROM orders").fetchall() == [(92,)]
