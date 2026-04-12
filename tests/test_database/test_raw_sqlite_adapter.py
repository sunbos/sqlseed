from __future__ import annotations

from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter


class TestRawSQLiteAdapter:
    def test_connect_and_close(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        adapter.close()

    def test_get_table_names(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            tables = adapter.get_table_names()
            assert "users" in tables
            assert "orders" in tables
        finally:
            adapter.close()

    def test_get_column_info(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            columns = adapter.get_column_info("users")
            assert len(columns) > 0
            col_names = [c.name for c in columns]
            assert "id" in col_names
            assert "name" in col_names
        finally:
            adapter.close()

    def test_get_primary_keys(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            pks = adapter.get_primary_keys("users")
            assert "id" in pks
        finally:
            adapter.close()

    def test_get_foreign_keys(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            fks = adapter.get_foreign_keys("orders")
            assert len(fks) > 0
            assert fks[0].column == "user_id"
        finally:
            adapter.close()

    def test_batch_insert(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            data = iter([{"name": f"user_{i}", "email": f"u{i}@t.com"} for i in range(10)])
            inserted = adapter.batch_insert("users", data, batch_size=5)
            assert inserted == 10
            count = adapter.get_row_count("users")
            assert count == 10
        finally:
            adapter.close()

    def test_batch_insert_large(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            data = iter([{"name": f"user_{i}", "email": f"u{i}@t.com"} for i in range(25)])
            inserted = adapter.batch_insert("users", data, batch_size=10)
            assert inserted == 25
        finally:
            adapter.close()

    def test_clear_table(self, tmp_db_with_data) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db_with_data)
        try:
            assert adapter.get_row_count("users") == 10
            adapter.clear_table("users")
            assert adapter.get_row_count("users") == 0
        finally:
            adapter.close()

    def test_get_column_values(self, tmp_db_with_data) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db_with_data)
        try:
            values = adapter.get_column_values("users", "name")
            assert len(values) == 10
        finally:
            adapter.close()

    def test_context_manager(self, tmp_db) -> None:
        with RawSQLiteAdapter() as adapter:
            adapter.connect(tmp_db)
            tables = adapter.get_table_names()
            assert len(tables) > 0

    def test_optimize_and_restore(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            adapter.optimize_for_bulk_write(1000)
            adapter.restore_settings()
        finally:
            adapter.close()

    def test_is_autoincrement(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            columns = adapter.get_column_info("users")
            id_col = next(c for c in columns if c.name == "id")
            assert id_col.is_autoincrement is True
        finally:
            adapter.close()

    def test_fetch_pragma(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            result = adapter._fetch_pragma("journal_mode")
            assert result is not None
        finally:
            adapter.close()
