"""Rootdir-level pytest fixtures shared across core and plugin test suites.

This conftest.py lives at the repository rootdir (next to ``pyproject.toml``)
so that pytest auto-discovers it for ALL test files — both ``tests/`` and
``plugins/*/tests/``. This is the standard pytest monorepo pattern for
sharing fixtures across sibling test trees without ``pytest_plugins``.

Background: the previous design kept fixtures in ``tests/conftest.py`` and
used ``pytest_plugins = ["tests.conftest"]`` in plugin conftests to share
them. That caused ``ValueError: Plugin already registered under a different
name`` because pytest auto-discovers ``tests/conftest.py`` by path AND then
re-registers it by dotted name. Moving fixtures to this rootdir conftest
removes the need for ``pytest_plugins`` entirely: every test file sees
these fixtures via plain conftest discovery.

Helper functions (``make_column_info``, ``create_simple_db``,
``apply_enrichment``, ``create_project_info_db``) remain in
``tests/conftest.py`` and are imported explicitly by test files via
``from tests.conftest import ...``.
"""

from __future__ import annotations

import gc
import json
import os
import sqlite3
import urllib.request
from typing import TYPE_CHECKING

import pytest

from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter

try:
    from testcontainers.postgres import PostgresContainer
except ImportError:
    PostgresContainer = None

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture
def gc_between_tests():
    """Opt-in garbage collection fixture for memory-sensitive tests.

    Use this fixture when a test needs explicit gc between setup/teardown.
    """
    gc.collect()
    yield
    gc.collect()


@pytest.fixture(name="tmp_db_simple")
def create_tmp_db_simple(tmp_path: Path) -> str:
    """Simple single-table database for lightweight tests."""
    db_path = str(tmp_path / "simple.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture(name="tmp_db_full")
def create_tmp_db_full(tmp_path: Path) -> str:
    """Full multi-table database with users + orders and FK constraints."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT,
            age INTEGER,
            phone TEXT,
            address TEXT,
            created_at TEXT,
            is_active INTEGER DEFAULT 1,
            balance REAL,
            bio TEXT,
            status INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_name TEXT,
            amount REAL,
            quantity INTEGER,
            status TEXT,
            created_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture(name="tmp_db")
def create_tmp_db(tmp_db_full: str) -> str:
    """Backward-compatible alias for tmp_db_full."""
    return tmp_db_full


@pytest.fixture(name="tmp_db_with_data")
def create_tmp_db_with_data(tmp_db: str) -> str:
    """tmp_db pre-populated with 10 user rows for tests needing existing data."""
    conn = sqlite3.connect(tmp_db)
    for i in range(10):
        conn.execute(
            "INSERT INTO users (name, email, age) VALUES (?, ?, ?)",
            [f"user_{i}", f"user_{i}@test.com", 20 + i],
        )
    conn.commit()
    conn.close()
    return tmp_db


@pytest.fixture(name="unique_test_db")
def create_unique_test_db(tmp_path: Path) -> str:
    """Database with projects table and unique indexes for UNIQUE constraint tests."""
    db_path = str(tmp_path / "unique_test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE projects (
            projectId INTEGER PRIMARY KEY AUTOINCREMENT,
            project_no VARCHAR(20) NOT NULL,
            member_no VARCHAR(32) NOT NULL,
            short_code VARCHAR(8),
            region_code VARCHAR(6),
            byProjectType INTEGER DEFAULT 1,
            byFirstProjectEnable INTEGER DEFAULT 0
        )
    """)
    conn.execute("CREATE UNIQUE INDEX idx_projectno ON projects(project_no)")
    conn.execute("CREATE UNIQUE INDEX idx_memberno ON projects(member_no)")
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture(name="raw_adapter")
def create_raw_adapter(tmp_db: str) -> Generator[RawSQLiteAdapter, None, None]:
    """RawSQLiteAdapter connected to tmp_db, yielded and closed on teardown."""
    adapter = RawSQLiteAdapter()
    adapter.connect(tmp_db)
    yield adapter
    adapter.close()


@pytest.fixture(name="raw_adapter_with_data")
def create_raw_adapter_with_data(tmp_db_with_data: str) -> Generator[RawSQLiteAdapter, None, None]:
    """RawSQLiteAdapter connected to tmp_db_with_data, yielded and closed on teardown."""
    adapter = RawSQLiteAdapter()
    adapter.connect(tmp_db_with_data)
    yield adapter
    adapter.close()


@pytest.fixture(scope="session")
def pg_url() -> Generator[str, None, None]:
    """Start a real PG container and return the connection URL. Fail with a hint if Docker is unavailable.

    Uses testcontainers to start a postgres:16-alpine container.
    Session-scoped fixture: all PG tests share a single container.
    """
    if PostgresContainer is None:
        pytest.skip("testcontainers package required for PG integration tests. Install: pip install testcontainers")
    try:
        pg = PostgresContainer("postgres:16-alpine")
        pg.start()
        # PostgresContainer.get_connection_url() returns postgresql+psycopg2://...,
        # but we have psycopg (v3) installed, so we need the postgresql+psycopg:// scheme
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
    """Detect available LLM backend. Fail with a hint if none is available.

    Fallback chain: Ollama -> LM Studio -> Google AI Studio.
    Returns {"backend": ..., "model": ...} where model is the Gemma 4 model ID for that backend.
    """
    # 1. Ollama — check /api/tags and verify that a gemma4 model has been pulled
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as resp:
            tags = json.loads(resp.read())
            models = {m.get("name", "") for m in tags.get("models", [])}
            for preferred in ("gemma4:26b", "gemma4:31b", "gemma4:e4b", "gemma4:12b"):
                if any(m.startswith(preferred) for m in models):
                    return {"backend": "ollama", "model": preferred}
            pytest.fail(
                "Ollama is running but no Gemma 4 model has been pulled. Please run:\n"
                "  ollama pull gemma4:26b   # recommended (requires 16GB VRAM)\n"
                "  ollama pull gemma4:e4b   # lightweight alternative (requires 4GB RAM)"
            )
    except (OSError, ValueError, KeyError):
        # Backend not running or unreachable (URLError is OSError subclass,
        # JSONDecodeError is ValueError subclass). pytest.fail() must NOT be
        # caught here — it raises Failed(Exception) which propagates correctly.
        pass

    # 2. LM Studio — check /v1/models and verify that a gemma-4 model has been loaded
    try:
        with urllib.request.urlopen("http://localhost:1234/v1/models", timeout=2) as resp:
            data = json.loads(resp.read())
            model_ids = {m.get("id", "") for m in data.get("data", [])}
            for preferred in (
                "google/gemma-4-26b-a4b",
                "google/gemma-4-31b",
                "google/gemma-4-e4b",
                "google/gemma-4-e2b",  # ultra-light edge model
            ):
                if preferred in model_ids:
                    return {"backend": "lm_studio", "model": preferred}
            pytest.skip(
                "LM Studio is running but no Gemma 4 model has been loaded. Please load in LM Studio:\n"
                "  google/gemma-4-26b-a4b   # recommended\n"
                "  google/gemma-4-e4b       # lightweight alternative\n"
                "  google/gemma-4-e2b       # ultra-light edge model"
            )
    except (OSError, ValueError, KeyError):
        pass

    # 3. Google AI Studio — check environment variable
    if os.environ.get("GOOGLE_API_KEY"):
        return {"backend": "google_ai_studio", "model": "gemma-4-26b-a4b-it"}

    pytest.skip(
        "At least one LLM backend is required to run AI integration tests:\n"
        "  - Ollama: install (https://ollama.ai) and pull a Gemma 4 model:\n"
        "      ollama pull gemma4:26b   # recommended (requires 16GB VRAM)\n"
        "      ollama pull gemma4:e4b   # lightweight alternative (requires 4GB RAM)\n"
        "  - LM Studio: install and load a Gemma 4 model (google/gemma-4-26b-a4b)\n"
        "  - Google AI Studio: set the GOOGLE_API_KEY environment variable\n"
        "    (model: gemma-4-26b-a4b-it)"
    )
    # pytest.skip() raises NoReturn; this raise exists to make pylint's
    # inconsistent-return-statements check aware that all paths exit.
    raise RuntimeError("unreachable — pytest.skip above raises NoReturn")
