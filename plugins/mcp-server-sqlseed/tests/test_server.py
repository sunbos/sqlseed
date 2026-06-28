"""Tests for the MCP server tools.

Per ARCHITECTURE.md Section 3.4, mcp-server-sqlseed exposes only:
- ``sqlseed_generate_yaml``  (rule-driven, no LLM)
- ``sqlseed_execute_fill``

Schema inspection, the schema resource, and the Gemma 4 tools have been
moved to ``sqlseed-ai[mcp]`` (see plugins/sqlseed-ai/tests/test_mcp.py).
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
import yaml as yaml_module

from mcp_server_sqlseed.server import sqlseed_execute_fill, sqlseed_generate_yaml

if TYPE_CHECKING:
    from pathlib import Path


def _create_test_db(db_path: str) -> None:
    """Create a test database."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT, age INTEGER)"
    )
    conn.commit()
    conn.close()


class TestMCPTools:
    """Tests for the MCP server tools."""

    @pytest.fixture
    def test_db(self, tmp_path: Path) -> str:
        db_path = str(tmp_path / "mcp_test.db")
        _create_test_db(db_path)
        return db_path

    def test_sqlseed_generate_yaml_rule_driven(self, test_db: str) -> None:
        """generate_yaml tool returns valid rule-driven YAML without any LLM."""
        result = sqlseed_generate_yaml(test_db, "users")
        assert isinstance(result, str)
        assert len(result) > 0
        assert not result.startswith("# Error"), f"generate_yaml returned an error: {result[:200]}"

        parsed = yaml_module.safe_load(result)
        assert parsed is not None, f"generate_yaml returned invalid YAML: {result[:200]}"
        assert "tables" in parsed
        table_entry = parsed["tables"][0]
        assert table_entry["name"] == "users"
        # Rule-driven mapping: the email column should map to the email generator.
        col_entries = {c["name"]: c for c in table_entry["columns"]}
        assert "email" in col_entries, f"email column missing from YAML: {list(col_entries)}"
        assert col_entries["email"]["generator"] == "email"
        # id (autoincrement PK) is mapped to the "skip" generator so the DB default applies.
        assert col_entries.get("id", {}).get("generator") == "skip"

    def test_sqlseed_generate_yaml_round_trips_into_execute_fill(self, test_db: str) -> None:
        """The YAML emitted by generate_yaml is consumable by execute_fill."""
        yaml_str = sqlseed_generate_yaml(test_db, "users")
        result = sqlseed_execute_fill(test_db, "users", count=5, yaml_config=yaml_str)
        assert result.get("table_name") == "users"
        assert result.get("count") == 5

        conn = sqlite3.connect(test_db)
        cursor = conn.execute("SELECT COUNT(*) FROM users")
        assert cursor.fetchone()[0] == 5
        conn.close()

    def test_sqlseed_execute_fill_sqlite(self, test_db: str) -> None:
        """execute_fill tool actually writes data."""
        result = sqlseed_execute_fill(test_db, "users", count=10)
        assert result["table_name"] == "users"
        assert result["count"] == 10

        conn = sqlite3.connect(test_db)
        cursor = conn.execute("SELECT COUNT(*) FROM users")
        assert cursor.fetchone()[0] == 10
        conn.close()

    def test_sqlseed_execute_fill_count_correct(self, test_db: str) -> None:
        """Row count is correct after execute_fill."""
        sqlseed_execute_fill(test_db, "users", count=50)
        sqlseed_execute_fill(test_db, "users", count=30)
        # The second fill does not clear by default, so rows accumulate (50 + 30 = 80).
        conn = sqlite3.connect(test_db)
        cursor = conn.execute("SELECT COUNT(*) FROM users")
        total = cursor.fetchone()[0]
        conn.close()
        assert total == 80

    def test_tool_invalid_db_path_returns_error(self) -> None:
        """generate_yaml returns an error string on an invalid path."""
        result = sqlseed_generate_yaml("invalid_path_no_extension", "users")
        assert result.startswith("# Error")
        assert "Invalid database target" in result

    def test_tool_nonexistent_table_returns_error(self, test_db: str) -> None:
        """generate_yaml returns an error string on a nonexistent table."""
        result = sqlseed_generate_yaml(test_db, "nonexistent_table")
        assert result.startswith("# Error")
        assert "does not exist" in result

    def test_sqlseed_generate_yaml_pg(self, pg_url: str) -> None:
        """generate_yaml tool with a PostgreSQL URL (rule-driven)."""
        from sqlalchemy import create_engine, text  # noqa: PLC0415

        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE IF NOT EXISTS mcp_test (id SERIAL PRIMARY KEY, name TEXT, email TEXT)"))
            conn.commit()
        engine.dispose()

        result = sqlseed_generate_yaml(pg_url, "mcp_test")
        assert not result.startswith("# Error"), f"generate_yaml failed on PG: {result[:200]}"
        parsed = yaml_module.safe_load(result)
        assert parsed["tables"][0]["name"] == "mcp_test"

    def test_tool_url_passes_through(self, pg_url: str) -> None:
        """execute_fill passes a URL through to the orchestrator."""
        from sqlalchemy import create_engine, text  # noqa: PLC0415

        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE IF NOT EXISTS url_test (id SERIAL PRIMARY KEY, name TEXT)"))
            conn.commit()
        engine.dispose()

        result = sqlseed_execute_fill(pg_url, "url_test", count=3)
        assert result.get("table_name") == "url_test"
        assert result.get("count") == 3
