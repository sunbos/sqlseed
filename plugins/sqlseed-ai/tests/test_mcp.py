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

import sqlite3
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("mcp")
pytest.importorskip("sqlseed_ai.mcp")

from sqlseed_ai.mcp import (
    sqlseed_ai_generate_yaml,
    sqlseed_gemma4_agent_fill,
    sqlseed_gemma4_analyze,
    sqlseed_list_gemma_models,
)

if TYPE_CHECKING:
    from pathlib import Path


def _create_test_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT, age INTEGER)"
    )
    conn.commit()
    conn.close()


def _ai_available() -> bool:
    try:
        from sqlseed_ai.config import AIConfig  # noqa: PLC0415

        return AIConfig.from_env().has_real_api_key
    except ImportError:
        return False


class TestAiMcpTools:
    @pytest.fixture
    def test_db(self, tmp_path: Path) -> str:
        db_path = str(tmp_path / "ai_mcp_test.db")
        _create_test_db(db_path)
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

        if backend == "ollama":
            monkeypatch.setenv("SQLSEED_AI_BACKEND", "ollama")
            monkeypatch.setenv("SQLSEED_AI_BASE_URL", "http://localhost:11434/v1")
        elif backend == "lm_studio":
            monkeypatch.setenv("SQLSEED_AI_BACKEND", "lm_studio")
            monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:1234/v1")
            monkeypatch.setenv("OPENAI_API_KEY", "lm-studio")

        monkeypatch.setenv("SQLSEED_AI_MODEL", model)

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

        if backend == "ollama":
            monkeypatch.setenv("SQLSEED_AI_BACKEND", "ollama")
            monkeypatch.setenv("SQLSEED_AI_BASE_URL", "http://localhost:11434/v1")
        elif backend == "lm_studio":
            monkeypatch.setenv("SQLSEED_AI_BACKEND", "lm_studio")
            monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:1234/v1")
            monkeypatch.setenv("OPENAI_API_KEY", "lm-studio")

        monkeypatch.setenv("SQLSEED_AI_MODEL", model)

        result = sqlseed_gemma4_agent_fill(test_db, "users", count=10, model=model, backend=backend, max_retries=1)
        assert "table_name" in result, f"gemma4_agent_fill missing table_name: {result}"
        assert "error" not in result, f"gemma4_agent_fill returned an error: {result.get('error', '')}"
        assert result["table_name"] == "users"
