from __future__ import annotations

import sqlite3

from sqlseed.core.schema import SchemaInferrer
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter


class TestSchemaInferrer:
    def test_get_column_info(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            inferrer = SchemaInferrer(adapter)
            columns = inferrer.get_column_info("users")
            assert len(columns) > 0
            col_names = [c.name for c in columns]
            assert "id" in col_names
            assert "name" in col_names
            assert "email" in col_names
        finally:
            adapter.close()

    def test_get_table_names(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            inferrer = SchemaInferrer(adapter)
            tables = inferrer.get_table_names()
            assert "users" in tables
            assert "orders" in tables
        finally:
            adapter.close()

    def test_get_primary_keys(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            inferrer = SchemaInferrer(adapter)
            pks = inferrer.get_primary_keys("users")
            assert "id" in pks
        finally:
            adapter.close()

    def test_get_foreign_keys(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            inferrer = SchemaInferrer(adapter)
            fks = inferrer.get_foreign_keys("orders")
            assert len(fks) > 0
            assert fks[0].ref_table == "users"
        finally:
            adapter.close()

    def test_get_table_schema(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            inferrer = SchemaInferrer(adapter)
            schema = inferrer.get_table_schema("users")
            assert "id" in schema
            assert "name" in schema
        finally:
            adapter.close()

    def test_get_index_info(self, tmp_path) -> None:
        db_path = str(tmp_path / "idx_test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, code TEXT NOT NULL, name TEXT)")
        conn.execute("CREATE UNIQUE INDEX idx_code ON items(code)")
        conn.execute("CREATE INDEX idx_name ON items(name)")
        conn.commit()
        conn.close()

        adapter = RawSQLiteAdapter()
        adapter.connect(db_path)
        try:
            inferrer = SchemaInferrer(adapter)
            indexes = inferrer.get_index_info("items")
            assert len(indexes) == 2
            idx_map = {i.name: i for i in indexes}
            assert "idx_code" in idx_map
            assert idx_map["idx_code"].unique is True
            assert "code" in idx_map["idx_code"].columns
            assert "idx_name" in idx_map
            assert idx_map["idx_name"].unique is False
        finally:
            adapter.close()

    def test_get_sample_data(self, tmp_path) -> None:
        db_path = str(tmp_path / "sample_test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO items (name) VALUES ('a')")
        conn.execute("INSERT INTO items (name) VALUES ('b')")
        conn.execute("INSERT INTO items (name) VALUES ('c')")
        conn.commit()
        conn.close()

        adapter = RawSQLiteAdapter()
        adapter.connect(db_path)
        try:
            inferrer = SchemaInferrer(adapter)
            samples = inferrer.get_sample_data("items", limit=2)
            assert len(samples) <= 2
            if samples:
                assert "name" in samples[0]
        finally:
            adapter.close()

    def test_get_sample_data_empty_table(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            inferrer = SchemaInferrer(adapter)
            samples = inferrer.get_sample_data("users", limit=5)
            assert isinstance(samples, list)
        finally:
            adapter.close()
