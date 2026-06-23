"""Shared pytest fixtures for sqlseed tests."""

from __future__ import annotations

import gc
import sqlite3
from typing import TYPE_CHECKING

import pytest

from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.database._protocol import ColumnInfo
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _gc_between_tests():
    gc.collect()
    yield
    gc.collect()


def make_col(
    name: str,
    col_type: str = "TEXT",
    nullable: bool = False,
    default=None,
    is_pk: bool = False,
    is_auto: bool = False,
):
    return type(
        "Col",
        (),
        {
            "name": name,
            "type": col_type,
            "nullable": nullable,
            "default": default,
            "is_primary_key": is_pk,
            "is_autoincrement": is_auto,
        },
    )()


def make_column_info(
    name: str,
    col_type: str = "TEXT",
    nullable: bool = False,
    default=None,
    is_primary_key: bool = False,
    is_autoincrement: bool = False,
) -> ColumnInfo:
    return ColumnInfo(
        name=name,
        type=col_type,
        nullable=nullable,
        default=default,
        is_primary_key=is_primary_key,
        is_autoincrement=is_autoincrement,
    )


@pytest.fixture(name="tmp_db")
def create_tmp_db(tmp_path: Path) -> str:
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


@pytest.fixture(name="tmp_db_with_data")
def create_tmp_db_with_data(tmp_db: str) -> str:
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
    adapter = RawSQLiteAdapter()
    adapter.connect(tmp_db)
    yield adapter
    adapter.close()


@pytest.fixture(name="raw_adapter_with_data")
def create_raw_adapter_with_data(tmp_db_with_data: str) -> Generator[RawSQLiteAdapter, None, None]:
    adapter = RawSQLiteAdapter()
    adapter.connect(tmp_db_with_data)
    yield adapter
    adapter.close()


PROJECT_INFO_DDL = """
    CREATE TABLE project_info(
        projectId INTEGER PRIMARY KEY,
        project_no VARCHAR(32) NOT NULL,
        byProjectType INT8 DEFAULT 1,
        byFirstProjectEnable INT8 DEFAULT 0,
        member_no VARCHAR(32) NOT NULL,
        short_code VARCHAR(20) DEFAULT NULL,
        region_code VARCHAR(20) DEFAULT NULL
    )
"""

PROJECT_INFO_INDEXES = [
    "CREATE UNIQUE INDEX projectindex_project_info_1 ON project_info(project_no)",
    "CREATE INDEX projectindex_project_info_2 ON project_info(member_no)",
    "CREATE UNIQUE INDEX projectindex_project_info_3 ON project_info(short_code)",
    "CREATE UNIQUE INDEX projectindex_project_info_4 ON project_info(region_code)",
]


def create_simple_db(
    db_path: str,
    table_ddl: str = "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)",
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(table_ddl)
    conn.commit()
    conn.close()


def apply_enrichment(db_path: str, table_name: str, provider_name: str = "base"):
    with DataOrchestrator(db_path, provider_name=provider_name) as orch:
        orch._ensure_connected()
        column_infos = orch._schema.get_column_info(table_name)
        unique_cols = orch._schema.detect_unique_columns(table_name)
        specs = orch._mapper.map_columns(column_infos, enrich=True)
        assert orch._enrichment is not None
        specs = orch._enrichment.apply(table_name, specs, column_infos, unique_cols)
        return orch, specs


def create_project_info_db(
    db_path: str,
    with_data: bool = False,
    data_count: int = 50,
    project_type_mod: int = 2,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(PROJECT_INFO_DDL)
    for idx_sql in PROJECT_INFO_INDEXES:
        conn.execute(idx_sql)
    if with_data:
        for i in range(data_count):
            conn.execute(
                "INSERT INTO project_info "
                "(projectId, project_no, byProjectType, byFirstProjectEnable, member_no, short_code, region_code) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [i + 1, f"PRJ{i:04d}", (i % project_type_mod) + 1, i % 2, f"M{i:04d}", f"SC_{i:04d}", f"RC_{i:04d}"],
            )
    conn.commit()
    conn.close()


@pytest.fixture(scope="session")
def pg_url() -> Generator[str, None, None]:
    """Start a real PG container and return the connection URL. Fail with a hint if Docker is unavailable.

    Uses testcontainers to start a postgres:16-alpine container.
    Session-scoped fixture: all PG tests share a single container.
    """
    try:
        from testcontainers.postgres import PostgresContainer  # noqa: PLC0415
    except ImportError:
        pytest.fail("testcontainers package is required for PG integration tests. Install: pip install testcontainers")
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
            pytest.fail(
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
    import json  # noqa: PLC0415
    import os  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

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
    except Exception:
        pass

    # 2. LM Studio — check /v1/models and verify that a gemma-4 model has been loaded
    try:
        with urllib.request.urlopen("http://localhost:1234/v1/models", timeout=2) as resp:
            data = json.loads(resp.read())
            model_ids = {m.get("id", "") for m in data.get("data", [])}
            for preferred in ("google/gemma-4-26b-a4b", "google/gemma-4-31b", "google/gemma-4-e4b"):
                if preferred in model_ids:
                    return {"backend": "lm_studio", "model": preferred}
            pytest.skip(
                "LM Studio is running but no Gemma 4 model has been loaded. Please load in LM Studio:\n"
                "  google/gemma-4-26b-a4b   # recommended\n"
                "  google/gemma-4-e4b       # lightweight alternative"
            )
    except Exception:
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
