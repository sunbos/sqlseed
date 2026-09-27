"""Real PostgreSQL oracles for FK preflight, generation and batch rollback."""

from __future__ import annotations

import json
from contextlib import closing, contextmanager
from typing import TYPE_CHECKING

import pytest

import sqlseed
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter
from sqlseed.generators._protocol import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.integration


@contextmanager
def _schema(pg_url: str, statements: list[str], cleanup: list[str]) -> Iterator[SQLAlchemyAdapter]:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(pg_url)
        try:
            for statement in statements:
                adapter.execute(statement).close()
            yield adapter
        finally:
            for statement in cleanup:
                adapter.execute(statement).close()


def _fill_config(pg_url: str, tmp_path: Path, names: list[str]) -> list[sqlseed.GenerationResult]:
    path = tmp_path / "pg-generation.json"
    path.write_text(
        json.dumps({"url": pg_url, "provider": "base", "tables": [{"name": n, "count": 8, "seed": 42} for n in names]}),
        encoding="utf-8",
    )
    return sqlseed.fill_from_config(str(path), skip_ai=True)


def test_pg_multilevel_fk_generation_sorts_and_retains_integrity(pg_url: str, tmp_path: Path) -> None:
    ddl = [
        "CREATE TABLE audit_parent(id SERIAL PRIMARY KEY)",
        "CREATE TABLE audit_child(id SERIAL PRIMARY KEY, parent_id INTEGER NOT NULL REFERENCES audit_parent(id))",
        "CREATE TABLE audit_leaf(id SERIAL PRIMARY KEY, child_id INTEGER NOT NULL REFERENCES audit_child(id))",
    ]
    with _schema(pg_url, ddl, ["DROP TABLE IF EXISTS audit_leaf, audit_child, audit_parent"]) as adapter:
        results = _fill_config(pg_url, tmp_path, ["audit_leaf", "audit_child", "audit_parent"])
        assert [r.table_name for r in results] == ["audit_parent", "audit_child", "audit_leaf"]
        assert all(r.count == 8 and not r.errors for r in results)
        with closing(
            adapter.execute(
                "SELECT count(*) FROM audit_leaf l JOIN audit_child c ON c.id=l.child_id "
                "JOIN audit_parent p ON p.id=c.parent_id"
            )
        ) as cursor:
            assert cursor.fetchone() == (8,)


def test_pg_nullable_cycle_is_broken_without_invalid_references(pg_url: str, tmp_path: Path) -> None:
    ddl = [
        "CREATE TABLE audit_cycle_a(id SERIAL PRIMARY KEY, b_id INTEGER)",
        "CREATE TABLE audit_cycle_b(id SERIAL PRIMARY KEY, a_id INTEGER NOT NULL REFERENCES audit_cycle_a(id))",
        "ALTER TABLE audit_cycle_a ADD FOREIGN KEY(b_id) REFERENCES audit_cycle_b(id)",
    ]
    with _schema(pg_url, ddl, ["DROP TABLE IF EXISTS audit_cycle_a, audit_cycle_b"]) as adapter:
        results = _fill_config(pg_url, tmp_path, ["audit_cycle_b", "audit_cycle_a"])
        assert [r.table_name for r in results] == ["audit_cycle_a", "audit_cycle_b"]
        assert all(r.count == 8 and not r.errors for r in results)
        assert adapter.get_row_count("audit_cycle_a") == adapter.get_row_count("audit_cycle_b") == 8
        with closing(adapter.execute("SELECT count(*) FROM audit_cycle_a WHERE b_id IS NOT NULL")) as cursor:
            assert cursor.fetchone() == (0,)
        with closing(
            adapter.execute("SELECT count(*) FROM audit_cycle_b b JOIN audit_cycle_a a ON b.a_id=a.id")
        ) as cursor:
            assert cursor.fetchone() == (8,)


def test_pg_self_reference_second_phase_and_append_preserve_existing_rows(pg_url: str) -> None:
    ddl = ["CREATE TABLE audit_nodes(id SERIAL PRIMARY KEY, parent_id INTEGER REFERENCES audit_nodes(id))"]
    with (
        _schema(pg_url, ddl, ["DROP TABLE IF EXISTS audit_nodes"]),
        DataOrchestrator(pg_url, provider_name="base", optimize_pragma=False) as orch,
    ):
        first = orch.fill_table("audit_nodes", count=12, batch_size=4, seed=42, skip_ai=True)
        assert first.count == 12 and not first.errors
        rows = orch.query("SELECT * FROM audit_nodes ORDER BY id")
        assert rows[0]["parent_id"] is None
        assert any(row["parent_id"] is not None for row in rows)
        assert all(row["parent_id"] is None or row["parent_id"] < row["id"] for row in rows)
        appended = orch.fill_table("audit_nodes", count=4, seed=42, skip_ai=True)
        assert appended.count == 4 and not appended.errors
        assert orch.query("SELECT * FROM audit_nodes WHERE id<=12 ORDER BY id") == rows
        assert not orch.query(
            "SELECT n.id FROM audit_nodes n LEFT JOIN audit_nodes p ON p.id=n.parent_id "
            "WHERE n.parent_id IS NOT NULL AND p.id IS NULL"
        )


@pytest.mark.parametrize("qualified", [False, True])
def test_pg_unsupported_fk_preflight_preserves_rows_before_clear(pg_url: str, qualified: bool) -> None:
    if qualified:
        ddl = [
            "CREATE SCHEMA audit_external",
            "CREATE TABLE audit_external.parent(id INTEGER PRIMARY KEY)",
            "INSERT INTO audit_external.parent VALUES(7)",
            "CREATE TABLE audit_unsupported(id INTEGER PRIMARY KEY, a INTEGER REFERENCES audit_external.parent(id))",
            "INSERT INTO audit_unsupported VALUES(1,7)",
        ]
        cleanup = ["DROP TABLE IF EXISTS audit_unsupported", "DROP SCHEMA audit_external CASCADE"]
        reason = "schema-qualified foreign key"
    else:
        ddl = [
            "CREATE TABLE audit_tuple(a INTEGER,b INTEGER,PRIMARY KEY(a,b))",
            "INSERT INTO audit_tuple VALUES(7,8)",
            "CREATE TABLE audit_unsupported(id INTEGER PRIMARY KEY,a INTEGER,b INTEGER,"
            "FOREIGN KEY(a,b) REFERENCES audit_tuple(a,b))",
            "INSERT INTO audit_unsupported VALUES(1,7,8)",
        ]
        cleanup = ["DROP TABLE IF EXISTS audit_unsupported, audit_tuple"]
        reason = "PostgreSQL composite foreign key"
    with (
        _schema(pg_url, ddl, cleanup),
        DataOrchestrator(pg_url, provider_name="base", optimize_pragma=False) as orch,
    ):
        before = orch.query("SELECT * FROM audit_unsupported")
        with pytest.raises(ConfigurationError, match=reason):
            orch.fill_table("audit_unsupported", count=4, clear_before=True, skip_ai=True)
        assert orch.query("SELECT * FROM audit_unsupported") == before


def test_pg_midstream_failure_rolls_back_all_batches_and_releases_connection(pg_url: str) -> None:
    ddl = ["CREATE TABLE audit_rollback(id INTEGER PRIMARY KEY)", "INSERT INTO audit_rollback VALUES(99)"]

    def broken_rows() -> Iterator[dict[str, int]]:
        yield {"id": 1}
        yield {"id": 2}
        raise RuntimeError("synthetic stream failure")

    with _schema(pg_url, ddl, ["DROP TABLE IF EXISTS audit_rollback"]) as adapter:
        with pytest.raises(RuntimeError, match="synthetic stream failure"):
            adapter.batch_insert("audit_rollback", broken_rows(), batch_size=1)
        with closing(adapter.execute("SELECT id FROM audit_rollback ORDER BY id")) as cursor:
            assert cursor.fetchall() == [(99,)]
        assert adapter.batch_insert("audit_rollback", iter([{"id": 3}]), batch_size=1) == 1
        assert adapter.get_row_count("audit_rollback") == 2
