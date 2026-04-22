from __future__ import annotations

from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter


class TestRawSQLiteAdapter:
    def test_connect_and_close(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        adapter.close()

    def test_get_table_names(self, raw_adapter) -> None:
        tables = raw_adapter.get_table_names()
        assert "users" in tables
        assert "orders" in tables

    def test_get_column_info(self, raw_adapter) -> None:
        columns = raw_adapter.get_column_info("users")
        assert len(columns) > 0
        col_names = [c.name for c in columns]
        assert "id" in col_names
        assert "name" in col_names

    def test_get_primary_keys(self, raw_adapter) -> None:
        pks = raw_adapter.get_primary_keys("users")
        assert "id" in pks

    def test_get_foreign_keys(self, raw_adapter) -> None:
        fks = raw_adapter.get_foreign_keys("orders")
        assert len(fks) > 0
        assert fks[0].column == "user_id"

    def test_batch_insert(self, raw_adapter) -> None:
        data = iter([{"name": f"user_{i}", "email": f"u{i}@t.com"} for i in range(10)])
        inserted = raw_adapter.batch_insert("users", data, batch_size=5)
        assert inserted == 10
        count = raw_adapter.get_row_count("users")
        assert count == 10

    def test_batch_insert_large(self, raw_adapter) -> None:
        data = iter([{"name": f"user_{i}", "email": f"u{i}@t.com"} for i in range(25)])
        inserted = raw_adapter.batch_insert("users", data, batch_size=10)
        assert inserted == 25

    def test_clear_table(self, raw_adapter_with_data) -> None:
        assert raw_adapter_with_data.get_row_count("users") == 10
        raw_adapter_with_data.clear_table("users")
        assert raw_adapter_with_data.get_row_count("users") == 0

    def test_get_column_values(self, raw_adapter_with_data) -> None:
        values = raw_adapter_with_data.get_column_values("users", "name")
        assert len(values) == 10

    def test_context_manager(self, tmp_db) -> None:
        with RawSQLiteAdapter() as adapter:
            adapter.connect(tmp_db)
            tables = adapter.get_table_names()
            assert len(tables) > 0

    def test_optimize_and_restore(self, raw_adapter) -> None:
        raw_adapter.optimize_for_bulk_write(1000)
        raw_adapter.restore_settings()

    def test_is_autoincrement(self, raw_adapter) -> None:
        columns = raw_adapter.get_column_info("users")
        id_col = next(c for c in columns if c.name == "id")
        assert id_col.is_autoincrement is True

    def test_fetch_pragma(self, raw_adapter) -> None:
        result = raw_adapter._fetch_pragma("journal_mode")
        assert result is not None
