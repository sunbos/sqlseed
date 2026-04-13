from __future__ import annotations

import sqlite3

from sqlseed.core.relation import RelationResolver, SharedPool
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter


class TestRelationResolver:
    def test_get_foreign_keys(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            resolver = RelationResolver(adapter)
            fks = resolver.get_foreign_keys("orders")
            assert len(fks) > 0
            assert fks[0].column == "user_id"
            assert fks[0].ref_table == "users"
            assert fks[0].ref_column == "id"
        finally:
            adapter.close()

    def test_get_dependencies(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            resolver = RelationResolver(adapter)
            deps = resolver.get_dependencies("orders")
            assert "users" in deps
        finally:
            adapter.close()

    def test_topological_sort(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            resolver = RelationResolver(adapter)
            order = resolver.topological_sort(["orders", "users"])
            assert order.index("users") < order.index("orders")
        finally:
            adapter.close()

    def test_topological_sort_circular(self, tmp_path) -> None:
        db_path = str(tmp_path / "circular.db")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("""
            CREATE TABLE a (
                id INTEGER PRIMARY KEY,
                b_id INTEGER,
                FOREIGN KEY (b_id) REFERENCES b(id)
            )
        """)
        conn.execute("""
            CREATE TABLE b (
                id INTEGER PRIMARY KEY,
                a_id INTEGER,
                FOREIGN KEY (a_id) REFERENCES a(id)
            )
        """)
        conn.commit()
        conn.close()

        adapter = RawSQLiteAdapter()
        adapter.connect(db_path)
        try:
            resolver = RelationResolver(adapter)
            try:
                resolver.topological_sort(["a", "b"])
                raise AssertionError("Should have raised ValueError for circular dependency")
            except ValueError:
                pass
        finally:
            adapter.close()

    def test_resolve_foreign_key_values_no_match(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            resolver = RelationResolver(adapter)
            values = resolver.resolve_foreign_key_values("orders", "nonexistent_col")
            assert values == []
        finally:
            adapter.close()

    def test_resolve_foreign_key_values(self, tmp_db_with_data) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db_with_data)
        try:
            resolver = RelationResolver(adapter)
            values = resolver.resolve_foreign_key_values("orders", "user_id")
            assert len(values) == 10
        finally:
            adapter.close()

    def test_get_fk_info(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            resolver = RelationResolver(adapter)
            fk_info = resolver.get_fk_info("orders", "user_id")
            assert fk_info is not None
            assert fk_info.ref_table == "users"
        finally:
            adapter.close()

    def test_get_fk_info_no_match(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            resolver = RelationResolver(adapter)
            fk_info = resolver.get_fk_info("orders", "nonexistent_col")
            assert fk_info is None
        finally:
            adapter.close()

    def test_clear_cache(self, tmp_db) -> None:
        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        try:
            resolver = RelationResolver(adapter)
            resolver.get_foreign_keys("orders")
            assert len(resolver._fk_cache) > 0
            resolver.clear_cache()
            assert len(resolver._fk_cache) == 0
        finally:
            adapter.close()


class TestSharedPool:
    def test_register_and_get(self):
        pool = SharedPool()
        pool.register("account_id", ["U001", "U002"])
        assert pool.get("account_id") == ["U001", "U002"]

    def test_has(self):
        pool = SharedPool()
        assert not pool.has("account_id")
        pool.register("account_id", ["U001"])
        assert pool.has("account_id")

    def test_has_empty(self):
        pool = SharedPool()
        pool.register("account_id", [])
        assert not pool.has("account_id")

    def test_get_nonexistent(self):
        pool = SharedPool()
        assert pool.get("nonexistent") == []

    def test_merge_deduplicates(self):
        pool = SharedPool()
        pool.register("account_id", ["U001", "U002"])
        pool.merge("account_id", ["U002", "U003"])
        assert pool.get("account_id") == ["U001", "U002", "U003"]

    def test_merge_new_key(self):
        pool = SharedPool()
        pool.merge("account_id", ["U001"])
        assert pool.get("account_id") == ["U001"]

    def test_clear(self):
        pool = SharedPool()
        pool.register("account_id", ["U001"])
        pool.clear()
        assert not pool.has("account_id")
