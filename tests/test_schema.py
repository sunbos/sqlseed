from __future__ import annotations

import sqlite3
from typing import Any

from sqlseed.core.schema import SchemaInferrer
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter


class TestSchemaInferrer:
    def test_get_column_info(self, raw_adapter) -> None:
        inferrer = SchemaInferrer(raw_adapter)
        columns = inferrer.get_column_info("users")
        assert len(columns) > 0
        col_names = [c.name for c in columns]
        assert "id" in col_names
        assert "name" in col_names
        assert "email" in col_names

    def test_get_table_names(self, raw_adapter) -> None:
        inferrer = SchemaInferrer(raw_adapter)
        tables = inferrer.get_table_names()
        assert "users" in tables
        assert "orders" in tables

    def test_get_primary_keys(self, raw_adapter) -> None:
        inferrer = SchemaInferrer(raw_adapter)
        pks = inferrer.get_primary_keys("users")
        assert "id" in pks

    def test_get_foreign_keys(self, raw_adapter) -> None:
        inferrer = SchemaInferrer(raw_adapter)
        fks = inferrer.get_foreign_keys("orders")
        assert len(fks) > 0
        assert fks[0].ref_table == "users"

    def test_get_table_schema(self, raw_adapter) -> None:
        inferrer = SchemaInferrer(raw_adapter)
        schema = inferrer.get_table_schema("users")
        assert "id" in schema
        assert "name" in schema

    def test_get_index_info(self, tmp_path: Any) -> None:
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

    def test_get_sample_data(self, tmp_path: Any) -> None:
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

    def test_get_sample_data_empty_table(self, raw_adapter) -> None:
        inferrer = SchemaInferrer(raw_adapter)
        samples = inferrer.get_sample_data("users", limit=5)
        assert isinstance(samples, list)

    def test_profile_column_distribution_empty_table(self, raw_adapter) -> None:
        inferrer = SchemaInferrer(raw_adapter)
        profiles = inferrer.profile_column_distribution("users")
        assert not profiles

    def test_profile_column_distribution_with_data(self, raw_adapter_with_data) -> None:
        inferrer = SchemaInferrer(raw_adapter_with_data)
        profiles = inferrer.profile_column_distribution("users")
        assert len(profiles) > 0
        name_profile = next((p for p in profiles if p["column"] == "name"), None)
        assert name_profile is not None
        assert name_profile["distinct_count"] > 0
        assert name_profile["sample_size"] > 0

    def test_profile_column_distribution_with_nulls(self, tmp_path: Any) -> None:
        db_path = str(tmp_path / "null_test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, value INTEGER)")
        conn.execute("INSERT INTO items (name, value) VALUES ('a', 1)")
        conn.execute("INSERT INTO items (name, value) VALUES (NULL, 2)")
        conn.execute("INSERT INTO items (name, value) VALUES ('b', NULL)")
        conn.commit()
        conn.close()

        adapter = RawSQLiteAdapter()
        adapter.connect(db_path)
        try:
            inferrer = SchemaInferrer(adapter)
            profiles = inferrer.profile_column_distribution("items")
            name_profile = next((p for p in profiles if p["column"] == "name"), None)
            assert name_profile is not None
            assert name_profile["null_ratio"] > 0
        finally:
            adapter.close()
