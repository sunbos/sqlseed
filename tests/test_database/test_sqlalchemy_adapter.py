"""SQLAlchemyAdapter 契约测试。

验证 SQLAlchemyAdapter（SQLite 方言）满足 DatabaseAdapter 协议，
并与 RawSQLiteAdapter 行为一致。

这些测试不依赖环境变量 SQLSEED_USE_SQLALCHEMY，
直接实例化 SQLAlchemyAdapter 进行测试。
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from sqlseed.database._dialect import SQLiteDialect
from sqlseed.database._protocol import DatabaseAdapter
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(name="sa_adapter")
def create_sa_adapter(tmp_db: str) -> SQLAlchemyAdapter:
    """创建已连接的 SQLAlchemyAdapter。"""
    adapter = SQLAlchemyAdapter()
    adapter.connect(tmp_db)
    yield adapter
    adapter.close()


@pytest.fixture(name="sa_adapter_with_data")
def create_sa_adapter_with_data(tmp_db_with_data: str) -> SQLAlchemyAdapter:
    """创建已连接且有数据的 SQLAlchemyAdapter。"""
    adapter = SQLAlchemyAdapter()
    adapter.connect(tmp_db_with_data)
    yield adapter
    adapter.close()


class TestSQLAlchemyAdapterConnection:
    """连接和关闭测试。"""

    def test_connect_and_close(self, tmp_db: str) -> None:
        adapter = SQLAlchemyAdapter()
        adapter.connect(tmp_db)
        assert adapter._engine is not None
        adapter.close()
        assert adapter._engine is None

    def test_connect_with_file_path(self, tmp_db: str) -> None:
        """纯文件路径应自动转为 sqlite:/// URL。"""
        adapter = SQLAlchemyAdapter()
        adapter.connect(tmp_db)
        assert "sqlite:///" in adapter._db_url
        adapter.close()

    def test_connect_with_sqlite_url(self, tmp_db: str) -> None:
        """显式 sqlite:/// URL 也应正常工作。"""
        adapter = SQLAlchemyAdapter()
        adapter.connect(f"sqlite:///{tmp_db}")
        assert adapter._db_url == f"sqlite:///{tmp_db}"
        adapter.close()

    def test_context_manager(self, tmp_db: str) -> None:
        with SQLAlchemyAdapter() as adapter:
            adapter.connect(tmp_db)
            tables = adapter.get_table_names()
            assert len(tables) > 0

    def test_dialect_property(self, sa_adapter: SQLAlchemyAdapter) -> None:
        dialect = sa_adapter.dialect
        assert isinstance(dialect, SQLiteDialect)
        assert dialect.name == "sqlite"

    def test_bulk_optimizer_property(self, sa_adapter: SQLAlchemyAdapter) -> None:
        """SQLite 方言应提供 bulk_optimizer。"""
        assert sa_adapter.bulk_optimizer is not None

    def test_dialect_before_connect_raises(self) -> None:
        """未连接时访问 dialect 应抛出 RuntimeError。"""
        adapter = SQLAlchemyAdapter()
        with pytest.raises(RuntimeError, match="not connected"):
            _ = adapter.dialect


class TestSQLAlchemyAdapterSchema:
    """Schema 读取测试。"""

    def test_get_table_names(self, sa_adapter: SQLAlchemyAdapter) -> None:
        tables = sa_adapter.get_table_names()
        assert "users" in tables
        assert "orders" in tables

    def test_get_column_info(self, sa_adapter: SQLAlchemyAdapter) -> None:
        columns = sa_adapter.get_column_info("users")
        assert len(columns) > 0
        col_names = [c.name for c in columns]
        assert "id" in col_names
        assert "name" in col_names
        assert "email" in col_names

    def test_column_info_types(self, sa_adapter: SQLAlchemyAdapter) -> None:
        """验证类型归一化。"""
        columns = sa_adapter.get_column_info("users")
        col_map = {c.name: c for c in columns}

        # SQLite 类型应保持大写
        assert col_map["name"].type == "VARCHAR" or col_map["name"].type == "TEXT"
        assert col_map["age"].type == "INTEGER"

    def test_column_info_primary_key(self, sa_adapter: SQLAlchemyAdapter) -> None:
        columns = sa_adapter.get_column_info("users")
        id_col = next(c for c in columns if c.name == "id")
        assert id_col.is_primary_key is True
        assert id_col.is_autoincrement is True

    def test_column_info_nullable(self, sa_adapter: SQLAlchemyAdapter) -> None:
        columns = sa_adapter.get_column_info("users")
        name_col = next(c for c in columns if c.name == "name")
        assert name_col.nullable is False  # NOT NULL

        email_col = next(c for c in columns if c.name == "email")
        assert email_col.nullable is True

    def test_get_primary_keys(self, sa_adapter: SQLAlchemyAdapter) -> None:
        pks = sa_adapter.get_primary_keys("users")
        assert "id" in pks

    def test_get_foreign_keys(self, sa_adapter: SQLAlchemyAdapter) -> None:
        fks = sa_adapter.get_foreign_keys("orders")
        assert len(fks) > 0
        assert fks[0].column == "user_id"
        assert fks[0].ref_table == "users"
        assert fks[0].ref_column == "id"

    def test_get_row_count_empty(self, sa_adapter: SQLAlchemyAdapter) -> None:
        count = sa_adapter.get_row_count("users")
        assert count == 0

    def test_get_row_count_with_data(self, sa_adapter_with_data: SQLAlchemyAdapter) -> None:
        count = sa_adapter_with_data.get_row_count("users")
        assert count == 10

    def test_get_index_info(self, tmp_path: Path) -> None:
        """测试索引信息读取。"""
        db_path = str(tmp_path / "index_test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE test_table (
                id INTEGER PRIMARY KEY,
                name TEXT,
                email TEXT
            )
        """)
        conn.execute("CREATE UNIQUE INDEX idx_email ON test_table(email)")
        conn.execute("CREATE INDEX idx_name ON test_table(name)")
        conn.commit()
        conn.close()

        adapter = SQLAlchemyAdapter()
        adapter.connect(db_path)
        indexes = adapter.get_index_info("test_table")
        assert len(indexes) == 2

        idx_map = {i.name: i for i in indexes}
        assert "idx_email" in idx_map
        assert idx_map["idx_email"].unique is True
        assert "idx_name" in idx_map
        assert idx_map["idx_name"].unique is False
        adapter.close()


class TestSQLAlchemyAdapterData:
    """数据操作测试。"""

    def test_batch_insert(self, sa_adapter: SQLAlchemyAdapter) -> None:
        data = iter([{"name": f"user_{i}", "email": f"u{i}@t.com"} for i in range(10)])
        inserted = sa_adapter.batch_insert("users", data, batch_size=5)
        assert inserted == 10
        assert sa_adapter.get_row_count("users") == 10

    def test_batch_insert_large(self, sa_adapter: SQLAlchemyAdapter) -> None:
        data = iter([{"name": f"user_{i}", "email": f"u{i}@t.com"} for i in range(25)])
        inserted = sa_adapter.batch_insert("users", data, batch_size=10)
        assert inserted == 25

    def test_clear_table(self, sa_adapter_with_data: SQLAlchemyAdapter) -> None:
        assert sa_adapter_with_data.get_row_count("users") == 10
        sa_adapter_with_data.clear_table("users")
        assert sa_adapter_with_data.get_row_count("users") == 0

    def test_clear_table_resets_autoincrement(self, sa_adapter_with_data: SQLAlchemyAdapter) -> None:
        """验证 clear_table 重置 AUTOINCREMENT 序列（sqlite_sequence 表）。

        覆盖被删除的 test_sqlite_utils_adapter.py::test_clear_table_resets_autoincrement。
        """
        # 先确认有数据，且 id 已自增
        assert sa_adapter_with_data.get_row_count("users") == 10
        # 插入一行，获取当前自增 id
        data = iter([{"name": "probe", "email": "probe@t.com"}])
        sa_adapter_with_data.batch_insert("users", data)
        cursor = sa_adapter_with_data.execute("SELECT MAX(id) FROM users")
        max_id_before = cursor.fetchone()[0]
        assert max_id_before is not None and max_id_before > 0

        # 清空表（应重置 sqlite_sequence）
        sa_adapter_with_data.clear_table("users")

        # 再插入一行，id 应从 1 重新开始
        data = iter([{"name": "fresh", "email": "fresh@t.com"}])
        sa_adapter_with_data.batch_insert("users", data)
        cursor = sa_adapter_with_data.execute("SELECT id FROM users")
        new_id = cursor.fetchone()[0]
        assert new_id == 1, f"AUTOINCREMENT not reset, new id={new_id}"

    def test_get_column_values(self, sa_adapter_with_data: SQLAlchemyAdapter) -> None:
        values = sa_adapter_with_data.get_column_values("users", "name")
        assert len(values) == 10

    def test_get_sample_rows(self, sa_adapter_with_data: SQLAlchemyAdapter) -> None:
        rows = sa_adapter_with_data.get_sample_rows("users", limit=3)
        assert len(rows) == 3
        assert "name" in rows[0]


class TestSQLAlchemyAdapterOptimization:
    """性能优化测试。"""

    def test_optimize_and_restore(self, sa_adapter: SQLAlchemyAdapter) -> None:
        """验证 PRAGMA 优化和恢复。"""
        sa_adapter.optimize_for_bulk_write(expected_rows=200000)
        # 优化后应能正常写入
        data = iter([{"name": "test", "email": "test@t.com"}])
        sa_adapter.batch_insert("users", data)
        sa_adapter.restore_settings()
        assert sa_adapter.get_row_count("users") == 1


class TestSQLAlchemyAdapterProtocol:
    """协议满足性测试。"""

    def test_satisfies_database_adapter_protocol(self, sa_adapter: SQLAlchemyAdapter) -> None:
        """SQLAlchemyAdapter 满足 DatabaseAdapter 协议。"""
        assert isinstance(sa_adapter, DatabaseAdapter)


class TestSQLAlchemyAdapterExecute:
    """execute 方法测试。"""

    def test_execute_select(self, sa_adapter_with_data: SQLAlchemyAdapter) -> None:
        result = sa_adapter_with_data.execute("SELECT COUNT(*) FROM users")
        row = result.fetchone()
        assert row[0] == 10

    def test_execute_insert(self, sa_adapter: SQLAlchemyAdapter) -> None:
        sa_adapter.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            ("test_user", "test@test.com"),
        )
        assert sa_adapter.get_row_count("users") == 1
