"""Tests for the sqlseed-ai MCP server (LLM-driven tools).

Per ARCHITECTURE.md Section 3.3 and 7.4, the AI MCP server provides:
- ``sqlseed_ai_generate_yaml``  (LLM-driven YAML config)
- ``sqlseed_gemma4_analyze``    (Gemma 4 schema analysis)
- ``sqlseed_gemma4_agent_fill`` (end-to-end AI agent fill)
- ``sqlseed_list_gemma_models`` (model/backend listing)

These tools require the ``mcp`` SDK (install with ``pip install
'sqlseed-ai[mcp]'``) and, for the LLM-driven tools, a configured backend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

# Optional sqlseed-ai[mcp] / openai / mcp SDK imports. The try/except block
# is the standard pytest pattern for optional test deps — pylint exempts
# imports inside try/except from wrong-import-position/wrong-import-order.
# ``sqlseed_ai.mcp`` itself imports the optional ``mcp`` SDK, so a single
# try/except covers both ``sqlseed_ai`` and ``mcp`` availability.
try:
    from sqlseed_ai.config import AIConfig
    from sqlseed_ai.mcp import (
        sqlseed_ai_generate_yaml,
        sqlseed_gemma4_agent_fill,
        sqlseed_gemma4_analyze,
        sqlseed_list_gemma_models,
    )
except ImportError:
    # pytest.skip with allow_module_level=True raises NoReturn — mypy
    # understands the except branch does not fall through. No
    # importorskip + wrong-import-position disable needed.
    pytest.skip("sqlseed-ai[mcp] not installed", allow_module_level=True)

import httpx

from tests._helpers import clear_llm_env, configure_llm_backend_env, create_simple_users_db
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _ai_available() -> bool:
    try:
        return AIConfig.from_env().has_real_api_key
    except ImportError:
        return False


@pytest.fixture(name="no_ai_requests")
def fixture_no_ai_requests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Isolate configuration and fail at the HTTP boundary before any network I/O."""
    clear_llm_env(monkeypatch)
    settings = {
        "SQLSEED_AI_BACKEND": "openai_compat",
        "SQLSEED_AI_BASE_URL": "http://protocol.invalid/v1",
        "SQLSEED_AI_MODEL": "mcp-table-validation-test",
        "SQLSEED_AI_API_KEY": "protocol-test-key",
        "SQLSEED_AI_TOOL_CALLING_PROTOCOL": "none",
        "SQLSEED_CACHE_DIR": str(tmp_path / "cache"),
    }
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    requests: list[str] = []

    def reject_request(_transport: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        pytest.fail("Invalid table names must be rejected before an AI request")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", reject_request)
    return requests


@pytest.mark.parametrize("table_name", ["missing_users", "users; DROP TABLE users;--"])
@pytest.mark.parametrize(
    "tool",
    [sqlseed_ai_generate_yaml, sqlseed_gemma4_analyze, sqlseed_gemma4_agent_fill],
    ids=["generate-yaml", "analyze", "agent-fill"],
)
def test_invalid_table_is_rejected_before_ai_and_preserves_database(
    tmp_path: Path,
    no_ai_requests: list[str],
    tool: Callable[..., str | dict[str, object]],
    table_name: str,
) -> None:
    """Exercise real schema lookup, error conversion and the refiner's early guard."""
    db_path = tmp_path / "existing.db"
    with sqlite_connection(db_path) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, age INTEGER NOT NULL)")
        connection.execute("INSERT INTO users (id, age) VALUES (1, 37)")
    original = db_path.read_bytes()

    result = tool(str(db_path), table_name)

    if isinstance(result, str):
        assert result.startswith("# Error: ")
        error = result
    else:
        assert set(result) <= {"error", "model"}
        error = result["error"]
    assert isinstance(error, str)
    assert table_name in error
    if tool is sqlseed_gemma4_agent_fill and ";" in table_name:
        assert "contains dangerous characters and is rejected" in error
    else:
        assert "does not exist" in error
    assert not no_ai_requests
    assert db_path.read_bytes() == original
    with sqlite_connection(db_path) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall() == [("users",)]
        assert connection.execute("SELECT id, age FROM users").fetchall() == [(1, 37)]


class TestAiMcpTools:
    @pytest.fixture
    def test_db(self, tmp_path: Path) -> str:
        db_path = str(tmp_path / "ai_mcp_test.db")
        create_simple_users_db(db_path)
        return db_path

    def test_sqlseed_list_gemma_models(self) -> None:
        """list_gemma_models returns the model list."""
        result = sqlseed_list_gemma_models()
        assert "models" in result
        assert "backends" in result
        assert isinstance(result["models"], list)
        assert isinstance(result["backends"], list)

    def test_sqlseed_ai_generate_yaml_invalid_db(self) -> None:
        """generate_yaml returns an error string on an invalid path."""
        result = sqlseed_ai_generate_yaml("invalid_path_no_extension", "users")
        assert result.startswith("# Error")
        assert "Invalid database target" in result

    def test_sqlseed_gemma4_analyze_invalid_db(self) -> None:
        """gemma4_analyze returns an error dict on an invalid path."""
        result = sqlseed_gemma4_analyze("invalid_path_no_extension", "users")
        assert "error" in result
        assert "Invalid database target" in result["error"]

    def test_sqlseed_gemma4_agent_fill_invalid_db(self) -> None:
        """gemma4_agent_fill returns an error dict on an invalid path."""
        result = sqlseed_gemma4_agent_fill("invalid_path_no_extension", "users")
        assert "error" in result
        assert "Invalid database target" in result["error"]

    @pytest.mark.skipif(not _ai_available(), reason="sqlseed-ai API key not configured")
    def test_sqlseed_ai_generate_yaml_real_llm(self, test_db: str, available_llm_backend: dict[str, str]) -> None:
        """generate_yaml with a real LLM call returns valid YAML."""
        backend = available_llm_backend["backend"]
        model = available_llm_backend["model"]
        result = sqlseed_ai_generate_yaml(test_db, "users", max_retries=1, model=model, backend=backend)
        assert isinstance(result, str)
        assert not result.startswith("#"), f"generate_yaml failed: {result[:200]}"

    @pytest.mark.skipif(not _ai_available(), reason="sqlseed-ai API key not configured")
    def test_sqlseed_gemma4_analyze_real_llm(
        self, test_db: str, available_llm_backend: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """gemma4_analyze with a real LLM call."""
        backend = available_llm_backend["backend"]
        model = available_llm_backend["model"]

        configure_llm_backend_env(monkeypatch, backend, model)

        result = sqlseed_gemma4_analyze(test_db, "users", model=model, backend=backend)
        assert "error" not in result, f"gemma4_analyze returned an error: {result.get('error', '')}"
        if "config" in result:
            assert result["config"] is not None

    @pytest.mark.skipif(not _ai_available(), reason="sqlseed-ai API key not configured")
    def test_sqlseed_gemma4_agent_fill_real_llm(
        self, test_db: str, available_llm_backend: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """gemma4_agent_fill with a real LLM call."""
        backend = available_llm_backend["backend"]
        model = available_llm_backend["model"]

        configure_llm_backend_env(monkeypatch, backend, model)

        result = sqlseed_gemma4_agent_fill(test_db, "users", count=10, model=model, backend=backend, max_retries=1)
        assert "table_name" in result, f"gemma4_agent_fill missing table_name: {result}"
        assert "error" not in result, f"gemma4_agent_fill returned an error: {result.get('error', '')}"
        assert result["table_name"] == "users"
