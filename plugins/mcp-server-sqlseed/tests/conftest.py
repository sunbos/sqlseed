"""Shared pytest fixtures for MCP server tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture
def tmp_sqlite_db(tmp_path: Path) -> str:
    """Create a temporary SQLite database file for testing."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT)")
    conn.commit()
    conn.close()
    return str(db_path)


@pytest.fixture(scope="session")
def pg_url() -> Generator[str, None, None]:
    """Start a real PostgreSQL container and return the connection URL. Skip if Docker is unavailable.

    Uses testcontainers to start a postgres:16-alpine container.
    Session-scoped fixture: all PG tests share a single container.
    """
    try:
        from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError:
        pytest.skip("testcontainers package required for PG integration tests. Install: pip install testcontainers")
    try:
        pg = PostgresContainer("postgres:16-alpine")
        pg.start()
        url = pg.get_connection_url()
        url = url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
        yield url
        pg.stop()
    except Exception as e:
        if "docker" in str(e).lower() or "connection" in str(e).lower() or "daemon" in str(e).lower():
            pytest.skip(
                "Docker must be running to execute PostgreSQL integration tests.\n"
                "Install guide: https://docs.docker.com/get-docker/\n"
                f"Error details: {e}"
            )
        raise


@pytest.fixture(scope="session")
def available_llm_backend() -> dict[str, str]:
    """Detect an available LLM backend. Skip when none are reachable.

    Fallback chain: Ollama -> LM Studio -> Google AI Studio.
    Returns {"backend": ..., "model": ...} where model is the Gemma 4 model ID for that backend.
    """
    import json as json_mod  # noqa: PLC0415
    import os  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    # 1. Ollama: probe /api/tags and verify a gemma4 model has been pulled.
    # Network/OS errors mean the backend is not running; skip silently and try the next backend.
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as resp:
            tags = json_mod.loads(resp.read())
            models = {m.get("name", "") for m in tags.get("models", [])}
            for preferred in ("gemma4:26b", "gemma4:31b", "gemma4:e4b", "gemma4:12b"):
                if any(m.startswith(preferred) for m in models):
                    return {"backend": "ollama", "model": preferred}
    except (OSError, ConnectionError, RuntimeError):
        # Backend not running or unreachable; fall through to the next option.
        pass

    # 2. LM Studio: probe /v1/models and verify a gemma-4 model is loaded.
    # Same rationale: connection failures indicate the backend is unavailable.
    try:
        with urllib.request.urlopen("http://localhost:1234/v1/models", timeout=2) as resp:
            data = json_mod.loads(resp.read())
            model_ids = {m.get("id", "") for m in data.get("data", [])}
            for preferred in (
                "google/gemma-4-26b-a4b",
                "google/gemma-4-31b",
                "google/gemma-4-e4b",
                "google/gemma-4-e2b",  # ultra-light edge model
            ):
                if preferred in model_ids:
                    return {"backend": "lm_studio", "model": preferred}
    except (OSError, ConnectionError, RuntimeError):
        # Backend not running or unreachable; fall through to the next option.
        pass

    # 3. Google AI Studio: check for the API key environment variable.
    if os.environ.get("GOOGLE_API_KEY"):
        return {"backend": "google_ai_studio", "model": "gemma-4-26b-a4b-it"}

    pytest.skip(
        "At least one LLM backend is required for AI integration tests:\n"
        "  - Ollama: ollama pull gemma4:26b\n"
        "  - LM Studio: load google/gemma-4-26b-a4b\n"
        "  - Google AI Studio: set the GOOGLE_API_KEY environment variable"
    )
