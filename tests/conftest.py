from __future__ import annotations

import gc
import sqlite3
from typing import TYPE_CHECKING

import pytest

from sqlseed.core.orchestrator import DataOrchestrator
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
