from __future__ import annotations

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
