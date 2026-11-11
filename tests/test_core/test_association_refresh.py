"""Real-database regression coverage for explicit association source freshness."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing, contextmanager
from typing import TYPE_CHECKING

import pytest

from sqlseed._utils.sql_safe import quote_identifier
from sqlseed.config.models import ColumnAssociation, GeneratorConfig
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.generators._protocol import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def _association_config(db_path: Path, *, source_table: str = "parent", source_column: str = "id") -> GeneratorConfig:
    """Configure a child association without enabling SQLite bulk optimizations."""
    return GeneratorConfig(
        db_path=str(db_path),
        provider="base",
        optimize_pragma=False,
        associations=[
            ColumnAssociation(
                column_name="department_id",
                source_table=source_table,
                source_column=source_column,
                target_tables=["child"],
            ),
        ],
    )


def _database_digest(db_path: Path) -> str:
    """Hash the database to detect writes during previews or rejected fills."""
    return hashlib.sha256(db_path.read_bytes()).hexdigest()


@contextmanager
def _association_database(db_path: Path, schema: str) -> Iterator[sqlite3.Connection]:
    """Create committed fixtures and keep the observer connection open for the test."""
    with closing(sqlite3.connect(db_path)) as conn:
        conn.executescript(schema)
        conn.commit()
        yield conn


def _assert_priority_fill(
    config: GeneratorConfig, columns: dict[str, dict[str, object]], conn: sqlite3.Connection
) -> None:
    """Require the explicit or declared FK to override the configured association."""
    with DataOrchestrator.from_config(config) as live:
        result = live.fill_table("child", count=8, seed=17, columns=columns, skip_ai=True)
        assert result.count == 8 and not result.errors
    assert {row[0] for row in conn.execute("SELECT department_id FROM child")} == {901, 902}


@pytest.mark.parametrize("generator", ["integer", "foreign_key_or_integer"])
@pytest.mark.parametrize("unrelated_key", ["member_id", "department_id"])
def test_explicit_source_stays_fresh_and_table_scoped(tmp_path: Path, generator: str, unrelated_key: str) -> None:
    db_path = tmp_path / "workflow.sqlite"
    with closing(sqlite3.connect(db_path)) as conn:
        conn.executescript(
            f"""
            CREATE TABLE parent(member_id INTEGER PRIMARY KEY);
            CREATE TABLE unrelated({quote_identifier(unrelated_key)} INTEGER PRIMARY KEY);
            CREATE TABLE child(id INTEGER PRIMARY KEY, department_id INTEGER NOT NULL);
            CREATE TABLE sentinel(value TEXT);
            INSERT INTO parent VALUES(101), (102);
            INSERT INTO unrelated VALUES(9001);
            INSERT INTO child VALUES(1, 101);
            INSERT INTO sentinel VALUES('original');
            """
        )
        conn.commit()
        config = _association_config(db_path, source_column="member_id")
        columns = {"department_id": {"generator": generator, "strategy": "coverage", "null_ratio": 0}}
        with DataOrchestrator.from_config(config) as live:
            result = live.fill_table("unrelated", count=1, seed=20, skip_ai=True)
            assert result.count == 1 and not result.errors
            for stage in range(3):
                result = live.fill_table("parent", count=1, seed=21 + stage, skip_ai=True)
                assert result.count == 1 and not result.errors
                expected = {row[0] for row in conn.execute("SELECT member_id FROM parent")}
                before = conn.execute("SELECT * FROM child ORDER BY id").fetchall()
                digest = _database_digest(db_path)
                preview = live.preview_table("child", count=60, seed=30 + stage, columns=columns)
                assert _database_digest(db_path) == digest
                assert {row["department_id"] for row in preview} == expected
                result = live.fill_table(
                    "child", count=60, batch_size=7, seed=30 + stage, columns=columns, skip_ai=True
                )
                assert result.count == 60 and not result.errors
                after = conn.execute("SELECT * FROM child ORDER BY id").fetchall()
                assert after[: len(before)] == before
                values = [row[1] for row in after[len(before) :]]
                assert values == [row["department_id"] for row in preview]
                for start in range(0, 60, len(expected)):
                    assert set(values[start : start + len(expected)]) == expected
                orphan_count = conn.execute(
                    "SELECT COUNT(*) FROM child WHERE department_id NOT IN (SELECT member_id FROM parent)"
                ).fetchone()
                assert orphan_count == (0,)
                assert conn.execute("SELECT * FROM sentinel").fetchall() == [("original",)]
                assert conn.execute("PRAGMA foreign_key_list(child)").fetchall() == []
                assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]


def test_real_explicit_foreign_key_override_keeps_priority(tmp_path: Path) -> None:
    db_path = tmp_path / "override.sqlite"
    with closing(sqlite3.connect(db_path)) as conn:
        conn.executescript(
            """
            CREATE TABLE parent(id INTEGER PRIMARY KEY);
            INSERT INTO parent VALUES(101), (102);
            CREATE TABLE other(id INTEGER PRIMARY KEY);
            INSERT INTO other VALUES(901), (902);
            CREATE TABLE child(id INTEGER PRIMARY KEY, department_id INTEGER NOT NULL);
            """
        )
        conn.commit()
        config = _association_config(db_path)
        columns = {
            "department_id": {
                "generator": "foreign_key",
                "ref_table": "other",
                "ref_column": "id",
                "strategy": "coverage",
                "null_ratio": 0,
            },
        }
        _assert_priority_fill(config, columns, conn)
        assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]


@pytest.mark.parametrize("source", ["empty_source", "missing_source"])
def test_unavailable_source_cannot_use_unrelated_pool(tmp_path: Path, source: str) -> None:
    db_path = tmp_path / "unavailable.sqlite"
    with closing(sqlite3.connect(db_path)) as conn:
        conn.executescript(
            """
            CREATE TABLE empty_source(id INTEGER PRIMARY KEY);
            CREATE TABLE unrelated(department_id INTEGER PRIMARY KEY);
            INSERT INTO unrelated VALUES(901);
            CREATE TABLE child(id INTEGER PRIMARY KEY, department_id INTEGER NOT NULL);
            INSERT INTO child VALUES(1, 123);
            CREATE TABLE sentinel(value TEXT);
            INSERT INTO sentinel VALUES('original');
            """
        )
        conn.commit()
        config = _association_config(db_path, source_table=source)
        with DataOrchestrator.from_config(config) as live:
            result = live.fill_table("unrelated", count=1, skip_ai=True)
            assert result.count == 1 and not result.errors
            before = _database_digest(db_path)
            with pytest.raises(ConfigurationError, match="has no readable source values"):
                live.preview_table("child", count=5)
            with pytest.raises(ConfigurationError, match="has no readable source values"):
                live.fill_table("child", count=5, skip_ai=True)
            assert _database_digest(db_path) == before
        assert conn.execute("SELECT * FROM child").fetchall() == [(1, 123)]
        assert conn.execute("SELECT * FROM sentinel").fetchall() == [("original",)]
        assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]


def test_database_foreign_key_keeps_priority(tmp_path: Path) -> None:
    db_path = tmp_path / "declared.sqlite"
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(
            """
            CREATE TABLE parent(id INTEGER PRIMARY KEY);
            INSERT INTO parent VALUES(101), (102);
            CREATE TABLE other(id INTEGER PRIMARY KEY);
            INSERT INTO other VALUES(901), (902);
            CREATE TABLE child(id INTEGER PRIMARY KEY, department_id INTEGER NOT NULL REFERENCES other(id));
            """
        )
        conn.commit()
        config = _association_config(db_path)
        columns = {"department_id": {"generator": "foreign_key_or_integer", "strategy": "coverage", "null_ratio": 0}}
        _assert_priority_fill(config, columns, conn)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
