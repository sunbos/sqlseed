from __future__ import annotations

import sqlite3

import yaml

import sqlseed
from sqlseed.core.mapper import GeneratorSpec
from sqlseed.core.relation import RelationResolver, SharedPool
from sqlseed.database._protocol import ForeignKeyInfo
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter
from tests._helpers import assert_fk_integrity


class _FakeDB:
    def __init__(self, *, fks=None, column_values=None, primary_keys=None):
        self._fks = fks or []
        self._column_values = column_values or []
        self._primary_keys = primary_keys or []

    def get_foreign_keys(self, _table_name):
        return self._fks

    def get_column_values(self, _table_name, _column_name, limit=10000):
        return self._column_values[:limit]

    def get_primary_keys(self, _table_name):
        return self._primary_keys


class _FakeAssoc:
    def __init__(
        self,
        column_name="region",
        source_table="regions",
        source_column=None,
        target_tables=None,
        strategy="shared_pool",
    ):
        self.column_name = column_name
        self.source_table = source_table
        self.source_column = source_column
        self.target_tables = target_tables or ["orders"]
        self.strategy = strategy


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
        resolver = RelationResolver(
            _FakeDB(
                fks=[ForeignKeyInfo(column="dept_id", ref_table="departments", ref_column="id")],
                column_values=[1, 2, 3],
            ),
            SharedPool(),
        )
        specs = {"dept_id": GeneratorSpec(generator_name="foreign_key_or_integer")}
        result = resolver.resolve_foreign_keys("employees", specs)
        assert result["dept_id"].generator_name == "foreign_key"
        assert result["dept_id"].params["ref_table"] == "departments"

    def test_resolve_foreign_keys_without_fk(self):
        resolver = RelationResolver(_FakeDB(), SharedPool())
        specs = {"dept_id": GeneratorSpec(generator_name="foreign_key_or_integer")}
        result = resolver.resolve_foreign_keys("employees", specs)
        assert result["dept_id"].generator_name == "integer"

    def test_resolve_implicit_associations(self):
        pool = SharedPool()
        pool.register("account_id", [10, 20, 30])
        resolver = RelationResolver(_FakeDB(), pool)
        specs = {"account_id": GeneratorSpec(generator_name="foreign_key_or_integer")}
        result = resolver.resolve_implicit_associations("orders", specs)
        assert result["account_id"].generator_name == "foreign_key"
        assert result["account_id"].params["ref_table"] == "__shared_pool__"

    def test_resolve_implicit_associations_empty_pool(self):
        resolver = RelationResolver(_FakeDB(), SharedPool())
        specs = {"account_id": GeneratorSpec(generator_name="foreign_key_or_integer")}
        result = resolver.resolve_implicit_associations("orders", specs)
        assert result["account_id"].generator_name == "foreign_key_or_integer"

    def test_register_shared_pool(self):
        pool = SharedPool()
        resolver = RelationResolver(_FakeDB(column_values=["alice", "bob"], primary_keys=["id"]), pool)
        specs = {
            "name": GeneratorSpec(generator_name="string"),
            "id": GeneratorSpec(generator_name="skip"),
        }
        resolver.register_shared_pool("users", specs)
        assert pool.has("name")
        assert pool.has("id")


class TestNonIdFKDetection:
    def test_fk_constraint_on_non_id_column_upgraded(self):
        resolver = RelationResolver(
            _FakeDB(
                fks=[ForeignKeyInfo(column="category", ref_table="categories", ref_column="id")],
                column_values=[1, 2, 3],
            ),
            SharedPool(),
        )
        specs = {"category": GeneratorSpec(generator_name="integer", params={"min_value": 1, "max_value": 999999})}
        result = resolver.resolve_foreign_keys("products", specs)
        assert result["category"].generator_name == "foreign_key"
        assert result["category"].params["ref_table"] == "categories"
        assert result["category"].params["ref_column"] == "id"

    def test_fk_constraint_on_string_column_upgraded(self):
        resolver = RelationResolver(
            _FakeDB(
                fks=[ForeignKeyInfo(column="department", ref_table="departments", ref_column="code")],
                column_values=["ENG", "SALES", "HR"],
            ),
            SharedPool(),
        )
        specs = {"department": GeneratorSpec(generator_name="string", params={"min_length": 3, "max_length": 10})}
        result = resolver.resolve_foreign_keys("employees", specs)
        assert result["department"].generator_name == "foreign_key"
        assert result["department"].params["ref_table"] == "departments"

    def test_already_foreign_key_not_overridden(self):
        resolver = RelationResolver(
            _FakeDB(
                fks=[ForeignKeyInfo(column="dept_id", ref_table="departments", ref_column="id")],
                column_values=[1, 2, 3],
            ),
            SharedPool(),
        )
        specs = {"dept_id": GeneratorSpec(
            generator_name="foreign_key",
            params={"ref_table": "departments", "ref_column": "id"},
        )}
        result = resolver.resolve_foreign_keys("employees", specs)
        assert result["dept_id"].generator_name == "foreign_key"
        assert result["dept_id"].params["ref_table"] == "departments"
        assert result["dept_id"].params["ref_column"] == "id"

    def test_no_fk_constraint_not_upgraded(self):
        resolver = RelationResolver(_FakeDB(), SharedPool())
        specs = {"category": GeneratorSpec(generator_name="integer", params={"min_value": 1, "max_value": 999999})}
        result = resolver.resolve_foreign_keys("products", specs)
        assert result["category"].generator_name == "integer"

    def test_non_id_fk_integration(self, tmp_path):
        db_path = str(tmp_path / "non_id_fk.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute(
            "CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, category INTEGER REFERENCES categories(id))"
        )
        conn.commit()
        conn.close()

        with sqlseed.connect(db_path, provider="base") as orch:
            orch.fill_table(table_name="categories", count=5)
            result = orch.fill_table(table_name="products", count=10)
        assert result.count == 10

        conn = sqlite3.connect(db_path)
        cat_ids = {r[0] for r in conn.execute("SELECT id FROM categories").fetchall()}
        prod_cats = {r[0] for r in conn.execute("SELECT category FROM products").fetchall()}
        conn.close()

        assert prod_cats.issubset(cat_ids)


class TestAutoIncrementPKSharedPool:
    def test_pk_values_registered_to_shared_pool(self):
        pool = SharedPool()
        resolver = RelationResolver(_FakeDB(column_values=[1, 2, 3, 4, 5], primary_keys=["id"]), pool)
        specs = {
            "id": GeneratorSpec(generator_name="skip"),
            "name": GeneratorSpec(generator_name="string"),
        }
        resolver.register_shared_pool("users", specs)
        assert pool.has("id")
        assert pool.get("id") == [1, 2, 3, 4, 5]

    def test_non_pk_skip_column_not_registered(self):
        pool = SharedPool()
        resolver = RelationResolver(_FakeDB(column_values=["val1", "val2"], primary_keys=["id"]), pool)
        specs = {
            "id": GeneratorSpec(generator_name="skip"),
            "status": GeneratorSpec(generator_name="skip"),
        }
        resolver.register_shared_pool("users", specs)
        assert pool.has("id")
        assert not pool.has("status")

    def test_autoincrement_pk_implicit_association(self, tmp_path):
        db_path = str(tmp_path / "pk_pool.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE authors (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
        conn.execute(
            "CREATE TABLE books ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "title TEXT, "
            "author_id INTEGER REFERENCES authors(id))"
        )
        conn.commit()
        conn.close()

        with sqlseed.connect(db_path, provider="base") as orch:
            orch.fill_table(table_name="authors", count=5)
            orch.fill_table(table_name="books", count=20)

        conn = sqlite3.connect(db_path)
        author_ids = {r[0] for r in conn.execute("SELECT id FROM authors").fetchall()}
        book_author_ids = {
            r[0] for r in conn.execute("SELECT author_id FROM books WHERE author_id IS NOT NULL").fetchall()
        }
        conn.close()

        assert book_author_ids.issubset(author_ids)

    def test_same_name_pk_implicit_association_via_shared_pool(self, tmp_path):
        db_path = str(tmp_path / "same_name_pk.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE departments (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
        conn.execute("CREATE TABLE employees (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, id_department INTEGER)")
        conn.commit()
        conn.close()

        with sqlseed.connect(db_path, provider="base") as orch:
            orch.fill_table(table_name="departments", count=5)
            pool_after_dept = dict(orch._shared_pool.items())
            assert "id" in pool_after_dept, "Auto-increment PK 'id' should be in SharedPool"
            assert len(pool_after_dept["id"]) == 5


class TestColumnAssociationConfig:
    @staticmethod
    def _make_assoc_resolver_and_specs():
        pool = SharedPool()
        resolver = RelationResolver(_FakeDB(column_values=["US", "EU", "APAC"]), pool)
        resolver.set_associations([_FakeAssoc()])
        specs = {
            "region": GeneratorSpec(
                generator_name="string",
                params={"min_length": 2, "max_length": 10},
            )
        }
        return resolver, specs

    def test_apply_associations_basic(self):
        resolver, specs = self._make_assoc_resolver_and_specs()
        result = resolver.apply_associations("orders", specs)
        assert result["region"].generator_name == "foreign_key"
        assert result["region"].params["ref_table"] == "__shared_pool__"

    def test_apply_associations_source_table_not_affected(self):
        resolver, specs = self._make_assoc_resolver_and_specs()
        result = resolver.apply_associations("regions", specs)
        assert result["region"].generator_name == "string"

    def test_apply_associations_already_foreign_key_skipped(self):
        pool = SharedPool()
        resolver = RelationResolver(_FakeDB(column_values=[1, 2, 3]), pool)
        resolver.set_associations(
            [_FakeAssoc(column_name="dept_id", source_table="departments", target_tables=["employees"])]
        )
        specs = {
            "dept_id": GeneratorSpec(
                generator_name="foreign_key",
                params={
                    "ref_table": "departments",
                    "ref_column": "id",
                },
            )
        }
        result = resolver.apply_associations("employees", specs)
        assert result["dept_id"].generator_name == "foreign_key"
        assert result["dept_id"].params["ref_table"] == "departments"

    def test_associations_in_topological_sort(self):
        resolver = RelationResolver(_FakeDB(), SharedPool())
        resolver.set_associations([_FakeAssoc()])
        order = resolver.topological_sort(["orders", "regions"])
        assert order.index("regions") < order.index("orders")

    def test_fill_from_config_with_associations(self, tmp_path):
        db_path = str(tmp_path / "assoc_test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE regions (id INTEGER PRIMARY KEY, code TEXT NOT NULL, name TEXT)")
        conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, product TEXT, region TEXT)")
        conn.commit()
        conn.close()

        config_data = {
            "db_path": db_path,
            "provider": "base",
            "tables": [
                {
                    "name": "regions",
                    "count": 5,
                    "columns": [
                        {
                            "name": "code",
                            "generator": "string",
                            "params": {
                                "min_length": 2,
                                "max_length": 4,
                            },
                        },
                    ],
                },
                {
                    "name": "orders",
                    "count": 20,
                    "columns": [
                        {"name": "product", "generator": "string"},
                        {
                            "name": "region",
                            "generator": "foreign_key",
                            "params": {
                                "ref_table": "regions",
                                "ref_column": "code",
                            },
                        },
                    ],
                },
            ],
            "associations": [
                {
                    "column_name": "region",
                    "source_table": "regions",
                    "target_tables": ["orders"],
                    "strategy": "shared_pool",
                },
            ],
        }
        config_path = str(tmp_path / "config.yaml")
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        results = sqlseed.fill_from_config(config_path)
        assert len(results) == 2

        assert_fk_integrity(
            db_path,
            "SELECT region FROM orders WHERE region IS NOT NULL",
            "SELECT code FROM regions",
        )
