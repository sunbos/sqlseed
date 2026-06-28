"""Shared pytest helper functions for sqlseed tests.

Fixtures (``tmp_db``, ``unique_test_db``, ``pg_url``,
``available_llm_backend``, etc.) have been moved to the rootdir
``conftest.py`` at the repository root. The rootdir conftest is
auto-discovered by pytest for ALL test files (both ``tests/`` and
``plugins/*/tests/``), so fixtures are globally available without
``pytest_plugins``. This avoids both the "Plugin already registered"
error (caused by declaring a conftest as a pytest_plugin) and the
"pytest_plugins in non-top-level conftest is no longer supported"
restriction.

This module retains only helper functions (``make_column_info``,
``create_simple_db``, ``apply_enrichment``, ``create_project_info_db``)
that test files import directly via ``from tests.conftest import ...``.
"""

from __future__ import annotations

import sqlite3
import warnings

from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.database._protocol import ColumnInfo


def make_col(
    name: str,
    col_type: str = "TEXT",
    nullable: bool = False,
    default=None,
    is_pk: bool = False,
    is_auto: bool = False,
):
    """Deprecated. Use make_column_info instead."""
    warnings.warn(
        "make_col is deprecated and will be removed in a future version. Use make_column_info instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return make_column_info(
        name=name,
        col_type=col_type,
        nullable=nullable,
        default=default,
        is_primary_key=is_pk,
        is_autoincrement=is_auto,
    )


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


def make_col_info_varchar(
    name: str,
    col_type: str = "VARCHAR(50)",
    *,
    nullable: bool = True,
    default: object = None,
    is_primary_key: bool = False,
    is_autoincrement: bool = False,
) -> ColumnInfo:
    """Variant of :func:`make_column_info` with VARCHAR/nullable defaults.

    Used by ``test_plugin_mediator.py`` and ``test_unique_adjuster.py`` to
    avoid duplicating the ColumnInfo construction block (CodeFlow
    CodeDuplication). Defaults differ from :func:`make_column_info`:
    ``col_type="VARCHAR(50)"`` and ``nullable=True``.
    """
    return ColumnInfo(
        name=name,
        type=col_type,
        nullable=nullable,
        default=default,
        is_primary_key=is_primary_key,
        is_autoincrement=is_autoincrement,
    )


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
        if orch._enrichment is None:
            raise RuntimeError("Enrichment module not initialized")
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
