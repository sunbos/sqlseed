"""Tests for the MCP server tools and resources."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest

from mcp_server_sqlseed.server import sqlseed_inspect_schema

if TYPE_CHECKING:
    from pathlib import Path


def _ai_available() -> bool:
    """Check whether the sqlseed-ai plugin is available and an API key is configured."""
    try:
        from sqlseed_ai.config import AIConfig  # noqa: PLC0415

        config = AIConfig.from_env()
        return config.has_real_api_key
    except ImportError:
        return False


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

    def test_sqlseed_inspect_schema_sqlite(self, test_db: str) -> None:
        """inspect_schema tool returns the correct schema."""
        result = sqlseed_inspect_schema(test_db, "users")
        assert "users" in result
        cols = result["users"]["columns"]
        assert len(cols) >= 3
        col_names = [c["name"] for c in cols]
        assert "id" in col_names
        assert "name" in col_names

    def test_sqlseed_inspect_schema_pg(self, pg_url: str) -> None:
        """inspect_schema tool with a PostgreSQL URL."""
        from sqlalchemy import create_engine, text  # noqa: PLC0415

        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE IF NOT EXISTS mcp_test (id SERIAL PRIMARY KEY, name TEXT)"))
            conn.commit()
        engine.dispose()

        result = sqlseed_inspect_schema(pg_url, "mcp_test")
        assert "mcp_test" in result

    @pytest.mark.skipif(not _ai_available(), reason="sqlseed-ai plugin not installed or API key not configured")
    def test_sqlseed_generate_yaml_sqlite(self, test_db: str) -> None:
        """generate_yaml tool returns valid YAML."""
        from mcp_server_sqlseed.server import sqlseed_generate_yaml  # noqa: PLC0415

        result = sqlseed_generate_yaml(test_db, "users", max_retries=1)
        assert isinstance(result, str)
        assert len(result) > 0
        # Verify the returned value is valid YAML (parseable by yaml.safe_load).
        import yaml as yaml_module  # noqa: PLC0415

        parsed = yaml_module.safe_load(result)
        assert parsed is not None, f"generate_yaml returned invalid YAML: {result[:200]}"
        # Should contain the "tables" key (valid config structure).
        assert "tables" in parsed, (
            f"generate_yaml return value should contain the 'tables' key: "
            f"{list(parsed.keys()) if isinstance(parsed, dict) else 'N/A'}"
        )

    def test_sqlseed_execute_fill_sqlite(self, test_db: str) -> None:
        """execute_fill tool actually writes data."""
        from mcp_server_sqlseed.server import sqlseed_execute_fill  # noqa: PLC0415

        result = sqlseed_execute_fill(test_db, "users", count=10)
        assert result["table_name"] == "users"
        assert result["count"] == 10

        # Verify the data was actually written.
        conn = sqlite3.connect(test_db)
        cursor = conn.execute("SELECT COUNT(*) FROM users")
        assert cursor.fetchone()[0] == 10
        conn.close()

    def test_sqlseed_execute_fill_count_correct(self, test_db: str) -> None:
        """Row count is correct after execute_fill."""
        from mcp_server_sqlseed.server import sqlseed_execute_fill  # noqa: PLC0415

        sqlseed_execute_fill(test_db, "users", count=50)
        sqlseed_execute_fill(test_db, "users", count=30)
        # The second fill does not clear by default, so rows accumulate (50 + 30 = 80).
        conn = sqlite3.connect(test_db)
        cursor = conn.execute("SELECT COUNT(*) FROM users")
        total = cursor.fetchone()[0]
        conn.close()
        assert total == 80

    def test_sqlseed_gemma4_analyze_real_llm(
        self, test_db: str, available_llm_backend: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """gemma4_analyze with a real LLM call."""
        from mcp_server_sqlseed.server import sqlseed_gemma4_analyze  # noqa: PLC0415

        backend = available_llm_backend["backend"]
        model = available_llm_backend["model"]

        if backend == "ollama":
            monkeypatch.setenv("SQLSEED_AI_BACKEND", "ollama")
            monkeypatch.setenv("SQLSEED_AI_BASE_URL", "http://localhost:11434/v1")
        elif backend == "lm_studio":
            monkeypatch.setenv("SQLSEED_AI_BACKEND", "lm_studio")
            monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:1234/v1")
            monkeypatch.setenv("OPENAI_API_KEY", "lm-studio")
        elif backend == "google_ai_studio":
            pass

        monkeypatch.setenv("SQLSEED_AI_MODEL", model)

        result = sqlseed_gemma4_analyze(test_db, "users", model=model, backend=backend)
        # Should return a valid result without an "error" key.
        assert "error" not in result, f"gemma4_analyze returned an error: {result.get('error', '')}"
        # Should return a valid config.
        if "config" in result:
            assert result["config"] is not None, "gemma4_analyze returned a None config"

    def test_sqlseed_gemma4_agent_fill_real_llm(
        self, test_db: str, available_llm_backend: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """gemma4_agent_fill with a real LLM call."""
        from mcp_server_sqlseed.server import sqlseed_gemma4_agent_fill  # noqa: PLC0415

        backend = available_llm_backend["backend"]
        model = available_llm_backend["model"]

        if backend == "ollama":
            monkeypatch.setenv("SQLSEED_AI_BACKEND", "ollama")
            monkeypatch.setenv("SQLSEED_AI_BASE_URL", "http://localhost:11434/v1")
        elif backend == "lm_studio":
            monkeypatch.setenv("SQLSEED_AI_BACKEND", "lm_studio")
            monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:1234/v1")
            monkeypatch.setenv("OPENAI_API_KEY", "lm-studio")
        elif backend == "google_ai_studio":
            pass

        monkeypatch.setenv("SQLSEED_AI_MODEL", model)

        result = sqlseed_gemma4_agent_fill(test_db, "users", count=10, model=model, backend=backend, max_retries=1)
        # Should return a valid result containing the "table_name" key and no "error" key.
        assert "table_name" in result, f"gemma4_agent_fill return value should contain the 'table_name' key: {result}"
        assert "error" not in result, f"gemma4_agent_fill returned an error: {result.get('error', '')}"
        assert result["table_name"] == "users"

    def test_sqlseed_list_gemma_models(self) -> None:
        """list_gemma_models returns the model list."""
        from mcp_server_sqlseed.server import sqlseed_list_gemma_models  # noqa: PLC0415

        result = sqlseed_list_gemma_models()
        assert "models" in result
        assert "backends" in result
        assert isinstance(result["models"], list)
        assert isinstance(result["backends"], list)

    def test_get_schema_resource(self, test_db: str) -> None:
        """get_schema_resource resource returns the schema."""
        from mcp_server_sqlseed.server import get_schema_resource  # noqa: PLC0415

        result = get_schema_resource(test_db, "users")
        # Returns a JSON string.
        data = json.loads(result)
        assert data["table_name"] == "users"
        assert "columns" in data

    def test_tool_invalid_db_path_raises(self) -> None:
        """Tools raise correctly on an invalid path."""
        with pytest.raises(ValueError, match="Invalid database target"):
            sqlseed_inspect_schema("invalid_path_no_extension", "users")

    def test_tool_nonexistent_table_raises(self, test_db: str) -> None:
        """Tools raise correctly on a nonexistent table."""
        with pytest.raises(ValueError, match="does not exist"):
            sqlseed_inspect_schema(test_db, "nonexistent_table")

    def test_tool_url_passes_through(self, pg_url: str) -> None:
        """Tools pass a URL through to the orchestrator."""
        from sqlalchemy import create_engine, text  # noqa: PLC0415

        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE IF NOT EXISTS url_test (id SERIAL PRIMARY KEY, name TEXT)"))
            conn.commit()
        engine.dispose()

        # The URL should be passed through directly without raising a _validate_db_target error.
        result = sqlseed_inspect_schema(pg_url, "url_test")
        assert "url_test" in result
