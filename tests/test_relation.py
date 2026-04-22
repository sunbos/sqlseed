from __future__ import annotations

import sqlite3

from sqlseed.core.mapper import GeneratorSpec
from sqlseed.core.relation import RelationResolver, SharedPool
from sqlseed.database._protocol import ForeignKeyInfo
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter


class TestRelationResolver:
    def test_get_foreign_keys(self, raw_adapter) -> None:
        resolver = RelationResolver(raw_adapter)
        fks = resolver.get_foreign_keys("orders")
        assert len(fks) > 0
        assert fks[0].column == "user_id"
        assert fks[0].ref_table == "users"
        assert fks[0].ref_column == "id"

    def test_get_dependencies(self, raw_adapter) -> None:
        resolver = RelationResolver(raw_adapter)
        deps = resolver.get_dependencies("orders")
        assert "users" in deps

    def test_topological_sort(self, raw_adapter) -> None:
        resolver = RelationResolver(raw_adapter)
        order = resolver.topological_sort(["orders", "users"])
        assert order.index("users") < order.index("orders")

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

    def test_resolve_foreign_key_values_no_match(self, raw_adapter) -> None:
        resolver = RelationResolver(raw_adapter)
        values = resolver.resolve_foreign_key_values("orders", "nonexistent_col")
        assert values == []

    def test_resolve_foreign_key_values(self, raw_adapter_with_data) -> None:
        resolver = RelationResolver(raw_adapter_with_data)
        values = resolver.resolve_foreign_key_values("orders", "user_id")
        assert len(values) == 10

    def test_get_fk_info(self, raw_adapter) -> None:
        resolver = RelationResolver(raw_adapter)
        fk_info = resolver.get_fk_info("orders", "user_id")
        assert fk_info is not None
        assert fk_info.ref_table == "users"

    def test_get_fk_info_no_match(self, raw_adapter) -> None:
        resolver = RelationResolver(raw_adapter)
        fk_info = resolver.get_fk_info("orders", "nonexistent_col")
        assert fk_info is None

    def test_clear_cache(self, raw_adapter) -> None:
        resolver = RelationResolver(raw_adapter)
        resolver.get_foreign_keys("orders")
        assert len(resolver._fk_cache) > 0
        resolver.clear_cache()
        assert len(resolver._fk_cache) == 0


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


class TestRelationResolverFKMethods:
    def test_resolve_foreign_keys_with_fk(self):
        class FakeDB:
            def get_foreign_keys(self, _table_name):
                return [ForeignKeyInfo(column="dept_id", ref_table="departments", ref_column="id")]

            def get_column_values(self, _table_name, _column_name, limit=1000):
                _ = (self, _table_name, _column_name, limit)
                return [1, 2, 3]

        resolver = RelationResolver(FakeDB(), SharedPool())
        specs = {"dept_id": GeneratorSpec(generator_name="foreign_key_or_integer")}
        result = resolver.resolve_foreign_keys("employees", specs)
        assert result["dept_id"].generator_name == "foreign_key"
        assert result["dept_id"].params["ref_table"] == "departments"

    def test_resolve_foreign_keys_without_fk(self):
        class FakeDB:
            def get_foreign_keys(self, _table_name):
                _ = (self, _table_name)
                return []

            def get_column_values(self, _table_name, _column_name, limit=1000):
                _ = (self, _table_name, _column_name, limit)
                return []

        resolver = RelationResolver(FakeDB(), SharedPool())
        specs = {"dept_id": GeneratorSpec(generator_name="foreign_key_or_integer")}
        result = resolver.resolve_foreign_keys("employees", specs)
        assert result["dept_id"].generator_name == "integer"

    def test_resolve_implicit_associations(self):
        class FakeDB:
            def get_foreign_keys(self, _table_name):
                return []

        pool = SharedPool()
        pool.register("account_id", [10, 20, 30])
        resolver = RelationResolver(FakeDB(), pool)
        specs = {"account_id": GeneratorSpec(generator_name="foreign_key_or_integer")}
        result = resolver.resolve_implicit_associations("orders", specs)
        assert result["account_id"].generator_name == "foreign_key"
        assert result["account_id"].params["ref_table"] == "__shared_pool__"

    def test_resolve_implicit_associations_empty_pool(self):
        class FakeDB:
            def get_foreign_keys(self, _table_name):
                return []

        resolver = RelationResolver(FakeDB(), SharedPool())
        specs = {"account_id": GeneratorSpec(generator_name="foreign_key_or_integer")}
        result = resolver.resolve_implicit_associations("orders", specs)
        assert result["account_id"].generator_name == "foreign_key_or_integer"

    def test_register_shared_pool(self):
        class FakeDB:
            def get_foreign_keys(self, _table_name):
                return []

            def get_column_values(self, _table_name, _column_name, limit=10000):
                return ["alice", "bob"][:limit]

        pool = SharedPool()
        resolver = RelationResolver(FakeDB(), pool)
        specs = {
            "name": GeneratorSpec(generator_name="string"),
            "id": GeneratorSpec(generator_name="skip"),
        }
        resolver.register_shared_pool("users", specs)
        assert pool.has("name")
        assert not pool.has("id")
