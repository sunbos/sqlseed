from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import pytest

from sqlseed.core.enrichment import EnrichmentEngine
from sqlseed.core.mapper import ColumnMapper, GeneratorSpec
from sqlseed.core.schema import SchemaInferrer
from sqlseed.database.sqlite_utils_adapter import SQLiteUtilsAdapter
from tests.conftest import create_simple_db

if TYPE_CHECKING:
    from collections.abc import Generator as GeneratorType
    from pathlib import Path


class TestEnrichmentEngine:
    @staticmethod
    @contextmanager
    def _engine_from_db(db_path: str) -> GeneratorType[EnrichmentEngine, None, None]:
        adapter = SQLiteUtilsAdapter()
        adapter.connect(db_path)
        try:
            mapper = ColumnMapper()
            schema = SchemaInferrer(adapter)
            engine = EnrichmentEngine(adapter, mapper, schema)
            yield engine
        finally:
            adapter.close()

    @staticmethod
    @contextmanager
    def _engine_from_ddl(tmp_path: Path, ddl: str) -> GeneratorType[EnrichmentEngine, None, None]:
        db_path = str(tmp_path / "test.db")
        create_simple_db(db_path, ddl)
        with TestEnrichmentEngine._engine_from_db(db_path) as engine:
            yield engine

    def test_apply_no_enrich_specs(self, enrich_ctx) -> None:
        specs = {"name": GeneratorSpec(generator_name="string")}
        result = enrich_ctx.engine.apply("t", specs, enrich_ctx.schema.get_column_info("t"))
        assert result["name"].generator_name == "string"

    def test_apply_empty_table_skips_enrich(self, tmp_path: Any) -> None:
        with self._engine_from_ddl(tmp_path, "CREATE TABLE t (id INTEGER PRIMARY KEY, status TEXT)") as engine:
            specs = {"status": GeneratorSpec(generator_name="__enrich__")}
            result = engine.apply("t", specs, [])
            assert result["status"].generator_name == "skip"

    def test_apply_enumeration_column(self, tmp_path: Any) -> None:
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, user_status TEXT)")
        conn.executemany(
            "INSERT INTO t (user_status) VALUES (?)",
            [("active",)] * 80 + [("inactive",)] * 20,
        )
        conn.commit()
        conn.close()

        with self._engine_from_db(db_path) as engine:
            specs = {"user_status": GeneratorSpec(generator_name="__enrich__")}
            result = engine.apply("t", specs, [])
            assert result["user_status"].generator_name == "choice"
            assert "choices" in result["user_status"].params

    def test_apply_enrich_falls_back_to_mapper(self, tmp_path: Any) -> None:
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, email TEXT)")
        conn.executemany(
            "INSERT INTO t (email) VALUES (?)",
            [(f"user{i}@example.com",) for i in range(100)],
        )
        conn.commit()
        conn.close()

        with self._engine_from_db(db_path) as engine:
            specs = {"email": GeneratorSpec(generator_name="__enrich__")}
            result = engine.apply("t", specs, [])
            assert result["email"].generator_name != "__enrich__"

    def test_is_enumeration_column_by_name(self, enrich_ctx) -> None:
        assert enrich_ctx.engine.is_enumeration_column("user_status", None, 3, 100, False) is True
        assert enrich_ctx.engine.is_enumeration_column("email", None, 50, 100, False) is False
        assert enrich_ctx.engine.is_enumeration_column("id", None, 100, 100, True) is False

    def test_is_enumeration_column_zero_rows(self, tmp_path: Any) -> None:
        with self._engine_from_ddl(tmp_path, "CREATE TABLE t (id INTEGER PRIMARY KEY)") as engine:
            assert engine.is_enumeration_column("status", None, 0, 0, False) is False

    def test_apply_with_unique_column(self, tmp_path: Any) -> None:
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, code TEXT UNIQUE)")
        conn.executemany(
            "INSERT INTO t (code) VALUES (?)",
            [(f"CODE{i}",) for i in range(10)],
        )
        conn.commit()
        conn.close()

        with self._engine_from_db(db_path) as engine:
            specs = {"code": GeneratorSpec(generator_name="__enrich__")}
            result = engine.apply("t", specs, [], unique_columns={"code"})
            assert result["code"].generator_name != "__enrich__"
            assert result["code"].null_ratio == pytest.approx(0.0)
