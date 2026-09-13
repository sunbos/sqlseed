from __future__ import annotations

import sqlite3
from typing import Any

from sqlseed.core.schema import SchemaInferrer
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter


def _create_composite_pk_db(db_path: str) -> None:
    """创建含复合主键关联表的数据库（模拟 product_tags 场景）。"""
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
    conn.execute("CREATE TABLE tags (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
    conn.execute("""
        CREATE TABLE product_tags (
            product_id INTEGER NOT NULL REFERENCES products(id),
            tag_id INTEGER NOT NULL REFERENCES tags(id),
            PRIMARY KEY (product_id, tag_id)
        )
    """)
    conn.commit()
    conn.close()


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


class TestCompositePrimaryKeyDetection:
    """复合主键的 unique 检测：只有组合唯一，单列不应标为 unique。

    回归测试：此前 detect_unique_columns 把复合 PK 的每一列都加入
    unique_columns，导致关联表（如 product_tags）填充时单列被禁止复用，
    行数超过任一 FK 基数即失败。
    """

    def test_unique_columns_excludes_composite_pk_raw(self, tmp_path: Any) -> None:
        """RawSQLiteAdapter：复合 PK 列不得出现在 unique_columns 中。"""
        db_path = str(tmp_path / "composite_pk.db")
        _create_composite_pk_db(db_path)
        adapter = RawSQLiteAdapter()
        adapter.connect(db_path)
        try:
            inferrer = SchemaInferrer(adapter)
            unique_cols = inferrer.detect_unique_columns("product_tags")
            assert "product_id" not in unique_cols
            assert "tag_id" not in unique_cols
        finally:
            adapter.close()

    def test_unique_columns_excludes_composite_pk_sqlalchemy(self, tmp_path: Any) -> None:
        """SQLAlchemyAdapter（生产路径）：复合 PK 列不得出现在 unique_columns 中。"""
        db_path = str(tmp_path / "composite_pk_sa.db")
        _create_composite_pk_db(db_path)
        adapter = SQLAlchemyAdapter()
        adapter.connect(db_path)
        try:
            inferrer = SchemaInferrer(adapter)
            unique_cols = inferrer.detect_unique_columns("product_tags")
            assert "product_id" not in unique_cols
            assert "tag_id" not in unique_cols
        finally:
            adapter.close()

    def test_composite_unique_includes_composite_pk_sqlalchemy(self, tmp_path: Any) -> None:
        """SQLAlchemyAdapter：复合 PK 应被识别为复合 UNIQUE 约束。"""
        db_path = str(tmp_path / "composite_pk_sa2.db")
        _create_composite_pk_db(db_path)
        adapter = SQLAlchemyAdapter()
        adapter.connect(db_path)
        try:
            inferrer = SchemaInferrer(adapter)
            composite = inferrer.detect_composite_unique_constraints("product_tags")
            assert ["product_id", "tag_id"] in composite
        finally:
            adapter.close()


class TestInlineUniqueWithCheckDetection:
    """行内 UNIQUE 列同时带 CHECK 约束时的单列 UNIQUE 检测。

    回归测试：SQLAlchemy 的 inspector.get_unique_constraints 在该组合下可能
    （SQLite 反射限制）丢失自动索引，导致 year/rating 未被识别为 UNIQUE 列，
    填充时生成重复值违反约束。修复：get_unique_constraints 用 PRAGMA 补充。
    """

    def test_inline_unique_with_check_single_column_sqlalchemy(self, tmp_path: Any) -> None:
        """SQLAlchemyAdapter（生产路径）：UNIQUE+CHECK 列应被识别为单列 UNIQUE。"""
        db_path = str(tmp_path / "inline_unique_check.db")
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """CREATE TABLE "t1" (
                "id" INTEGER NOT NULL,
                "price" REAL NOT NULL CHECK (price >= 0),
                "year" INTEGER NOT NULL UNIQUE CHECK (year >= 2000 AND year <= 2026),
                "priority" TEXT NOT NULL CHECK (priority IN ('low','medium','high')),
                "rating" REAL NOT NULL UNIQUE CHECK (rating >= 0),
                PRIMARY KEY ("id")
            );"""
        )
        conn.commit()
        conn.close()
        adapter = SQLAlchemyAdapter()
        adapter.connect(db_path)
        try:
            inferrer = SchemaInferrer(adapter)
            unique_cols = inferrer.detect_unique_columns("t1")
            assert "year" in unique_cols
            assert "rating" in unique_cols
        finally:
            adapter.close()

    def test_inline_unique_with_check_single_column_raw(self, tmp_path: Any) -> None:
        """RawSQLiteAdapter：UNIQUE+CHECK 列应被识别为单列 UNIQUE（PRAGMA 路径）。"""
        db_path = str(tmp_path / "inline_unique_check_raw.db")
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """CREATE TABLE "t1" (
                "id" INTEGER NOT NULL,
                "year" INTEGER NOT NULL UNIQUE CHECK (year >= 2000 AND year <= 2026),
                "rating" REAL NOT NULL UNIQUE CHECK (rating >= 0),
                PRIMARY KEY ("id")
            );"""
        )
        conn.commit()
        conn.close()
        adapter = RawSQLiteAdapter()
        adapter.connect(db_path)
        try:
            inferrer = SchemaInferrer(adapter)
            unique_cols = inferrer.detect_unique_columns("t1")
            assert "year" in unique_cols
            assert "rating" in unique_cols
        finally:
            adapter.close()
