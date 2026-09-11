"""Real database coverage for workbench schema and generator metadata."""

from __future__ import annotations

import importlib
import inspect
import json
import sqlite3
from contextlib import closing, nullcontext
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy.exc import SAWarning
from sqlseed.generators._dispatch import GeneratorDispatchMixin
from sqlseed.generators.base_provider import BaseProvider

from sqlseed_web.state import Connection, UIState

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from types import ModuleType


def _workbench() -> ModuleType:
    assert importlib.util.find_spec("sqlseed_web.workbench_schema") is not None, "Workbench schema API is missing"
    return importlib.import_module("sqlseed_web.workbench_schema")


@pytest.fixture()
def connection(tmp_path: Path) -> Iterator[Connection]:
    path = tmp_path / "workbench.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript("""
            CREATE TABLE accounts (
                tenant INTEGER NOT NULL,
                code TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT 'account',
                PRIMARY KEY (tenant, code),
                CONSTRAINT uq_account_name UNIQUE (tenant, name)
            );
            CREATE TABLE entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant INTEGER NOT NULL,
                account_code TEXT NOT NULL,
                optional_tenant INTEGER,
                optional_code TEXT,
                amount INTEGER NOT NULL DEFAULT 1,
                doubled INTEGER GENERATED ALWAYS AS (amount * 2) STORED,
                CONSTRAINT positive_amount CHECK (amount > 0),
                CONSTRAINT account_fk FOREIGN KEY (tenant, account_code) REFERENCES accounts (tenant, code),
                CONSTRAINT optional_account_fk FOREIGN KEY (optional_tenant, optional_code)
                    REFERENCES accounts (tenant, code)
            );
            CREATE TABLE missing_reference (id INTEGER PRIMARY KEY, external_id INTEGER REFERENCES absent (id));
            INSERT INTO accounts (tenant, code) VALUES (1, 'A');
            INSERT INTO entries (tenant, account_code) VALUES (1, 'A');
        """)
    registry = UIState()
    conn = registry.add_connection(str(path), provider="base", locale="zh_CN")
    yield conn
    registry.close_connection(conn.conn_id)


def _tables(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {table["name"]: table for table in schema["tables"]}


def test_partial_unique_is_not_a_global_rule_and_accepts_outside_predicate_rows(connection: Connection) -> None:
    from sqlseed_web.workbench_runtime import check_document

    with closing(sqlite3.connect(connection.target)) as db, db:
        db.executescript(
            "CREATE TABLE archived_items(code TEXT NOT NULL, archived INTEGER NOT NULL);"
            "CREATE UNIQUE INDEX active_code ON archived_items(code) WHERE archived = 0;"
            "INSERT INTO archived_items VALUES('same',1),('same',1);"
        )
        assert db.execute("SELECT code,archived FROM archived_items").fetchall() == [("same", 1), ("same", 1)]
    schema = _workbench().inspect_connection(connection)
    table = _tables(schema)["archived_items"]
    assert table["unique_constraints"] == []
    assert table["conditional_indexes"] == [
        {"name": "active_code", "columns": ["code"], "unique": True, "predicate": "archived = 0"}
    ]
    checked = check_document(
        connection,
        {
            "provider": "base",
            "tables": [
                {
                    "name": "archived_items",
                    "count": 2,
                    "columns": [
                        {"name": "code", "generator": "choice", "params": {"choices": ["same"]}},
                        {"name": "archived", "generator": "integer", "params": {"min_value": 1, "max_value": 1}},
                    ],
                }
            ],
        },
        schema["schema_hash"],
        count=2,
        preview=True,
    )
    assert checked["ok"], checked
    assert checked["samples"]["archived_items"] == [{"code": "same", "archived": 1}] * 2
    assert connection.orchestrator.get_row_count("archived_items") == 2


def test_changing_only_partial_index_predicate_changes_schema_hash(connection: Connection) -> None:
    with closing(sqlite3.connect(connection.target)) as db, db:
        db.executescript(
            "CREATE TABLE archived_items(code TEXT NOT NULL, archived INTEGER NOT NULL);"
            "CREATE UNIQUE INDEX active_code ON archived_items(code) WHERE archived = 0;"
        )
    before = _workbench().inspect_connection(connection)
    with closing(sqlite3.connect(connection.target)) as db, db:
        db.executescript(
            "DROP INDEX active_code; CREATE UNIQUE INDEX active_code ON archived_items(code) WHERE archived = 1;"
        )
    after = _workbench().inspect_connection(connection)
    assert after["schema_hash"] != before["schema_hash"]
    assert _tables(after)["archived_items"]["conditional_indexes"][0]["predicate"] == "archived = 1"


def test_inspection_contains_real_columns_constraints_and_mapping(connection: Connection) -> None:
    schema = _workbench().inspect_connection(connection)
    tables = _tables(schema)
    assert set(tables) == {"accounts", "entries", "missing_reference"}
    columns = {column["name"]: column for column in tables["entries"]["columns"]}
    assert list(columns) == ["id", "tenant", "account_code", "optional_tenant", "optional_code", "amount", "doubled"]
    assert columns["id"]["is_primary_key"] is True
    assert columns["id"]["is_autoincrement"] is True
    assert columns["amount"]["nullable"] is False
    assert columns["amount"]["default"] == "1"
    assert columns["doubled"]["is_computed"] is True
    assert tables["accounts"]["primary_key"] == ["tenant", "code"]
    assert {"name": "uq_account_name", "columns": ["tenant", "name"]} in tables["accounts"]["unique_constraints"]
    assert tables["entries"]["checks"] == [{"name": "positive_amount", "expression": "amount > 0"}]
    assert tables["entries"]["row_count"] == 1
    assert tables["accounts"]["mapping"]["code"]["generator_name"] == "string"
    assert schema["provider"] == "base"
    assert schema["locale"] == "zh_CN"
    assert schema["dialect"] == "sqlite"
    json.dumps(schema)


def test_composite_foreign_keys_remain_grouped_with_parent_to_child_edges(connection: Connection) -> None:
    schema = _workbench().inspect_connection(connection)
    fks = _tables(schema)["entries"]["foreign_keys"]
    assert len(fks) == 2
    required = next(fk for fk in fks if fk["columns"] == ["tenant", "account_code"])
    assert required["ref_columns"] == ["tenant", "code"]
    assert required["ref_table"] == "accounts"
    assert required["ref_schema"] is None
    assert required["nullable"] is False
    assert next(fk for fk in fks if fk is not required)["nullable"] is True
    edge = next(edge for edge in schema["edges"] if edge["id"] == required["id"])
    assert edge["source"] == "accounts"
    assert edge["target"] == "entries"
    assert edge["sourceColumns"] == ["tenant", "code"]
    assert edge["targetColumns"] == ["tenant", "account_code"]


def test_missing_reference_keeps_a_readonly_graph_node(connection: Connection) -> None:
    schema = _workbench().inspect_connection(connection)
    external = next(node for node in schema["nodes"] if node["id"] == "absent")
    assert external["readonly"] is True
    assert "absent" not in _tables(schema)
    assert any(edge["source"] == "absent" and edge["target"] == "missing_reference" for edge in schema["edges"])


def test_schema_hash_ignores_data_and_changes_after_ddl_with_existing_caches(connection: Connection) -> None:
    module = _workbench()
    before = module.inspect_connection(connection)
    connection.orchestrator.fill_table("accounts", count=1)
    after_data = module.inspect_connection(connection)
    assert before["schema_hash"] == after_data["schema_hash"]
    assert _tables(after_data)["accounts"]["row_count"] == 2
    with closing(sqlite3.connect(connection.target)) as db, db:
        db.execute("ALTER TABLE accounts ADD COLUMN added TEXT")
        db.execute("CREATE TABLE new_table (id INTEGER PRIMARY KEY)")
    after_ddl = module.inspect_connection(connection)
    assert after_ddl["schema_hash"] != before["schema_hash"]
    assert "new_table" in _tables(after_ddl)
    assert "added" in {column["name"] for column in _tables(after_ddl)["accounts"]["columns"]}
    assert "added" in connection.orchestrator.get_column_mapping("accounts")
    assert module.inspect_connection(connection)["schema_hash"] == after_ddl["schema_hash"]


def test_target_key_normalizes_sqlite_url_and_hides_network_credentials(connection: Connection) -> None:
    module = _workbench()
    plain = module.inspect_connection(connection)
    sqlite_url = module.inspect_connection(replace(connection, target=f"sqlite+pysqlite:///{connection.target}"))
    assert plain["target_key"] == sqlite_url["target_key"]
    secret_url = "postgresql://secret_user:secret_password@LOCALHOST:5432/demo?password=query_secret&sslmode=require"
    network = module.inspect_connection(replace(connection, target=secret_url))
    payload = json.dumps(network)
    assert "secret_user" not in payload
    assert "secret_password" not in payload
    assert "query_secret" not in payload
    assert "localhost" in network["target_label"].lower()
    assert len(network["target_key"]) == 64


def test_schema_refresh_invalidates_cached_dependency_order(connection: Connection) -> None:
    module = _workbench()
    module.inspect_connection(connection)
    assert connection.orchestrator.get_topological_table_order(["entries", "accounts"]) == ["accounts", "entries"]
    with closing(sqlite3.connect(connection.target)) as db, db:
        db.execute("DROP TABLE entries")
        db.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY)")
    schema = module.inspect_connection(connection)
    assert not _tables(schema)["entries"]["foreign_keys"]
    assert connection.orchestrator.get_topological_table_order(["entries", "accounts"]) == ["entries", "accounts"]


def test_target_key_ignores_driver_credentials_and_default_port(connection: Connection) -> None:
    module = _workbench()
    original = module.inspect_connection(
        replace(connection, target="postgresql://one:secret@LOCALHOST/demo?sslmode=require&password=first")
    )
    equivalent = module.inspect_connection(
        replace(
            connection, target="postgresql+psycopg://two:changed@localhost:5432/demo?password=second&sslmode=require"
        )
    )
    assert original["target_key"] == equivalent["target_key"]


def test_generator_catalog_matches_real_dispatch_and_signatures() -> None:
    result = _workbench().generator_catalog()
    assert result["names"] == sorted(GeneratorDispatchMixin.GENERATOR_MAP)
    assert "skip" not in result["names"]
    assert "foreign_key" not in result["names"]
    entries = {entry["id"]: entry for entry in result["entries"]}
    assert set(entries) == set(result["names"])
    for name, method_name in GeneratorDispatchMixin.GENERATOR_MAP.items():
        signature = inspect.signature(getattr(BaseProvider, method_name))
        expected = [param for param in signature.parameters if param != "self"]
        assert result["params"][name] == expected
        assert [param["name"] for param in entries[name]["params"]] == expected
        assert entries[name]["description"]
    integer = {param["name"]: param for param in entries["integer"]["params"]}
    assert integer["min_value"] == {"name": "min_value", "type": "integer", "required": False, "default": 0}
    choice = entries["choice"]["params"][0]
    assert choice["type"] == "array"
    assert choice["required"] is True
    assert entries["integer"]["output_type"] == "integer"
    assert entries["date"]["output_type"] == "date"
    json.dumps(result)


@pytest.mark.parametrize(
    ("declaration", "suffix", "is_rowid_alias", "is_autoincrement"),
    [
        ("id INTEGER PRIMARY KEY, value TEXT", "", True, False),
        ("id INTEGER PRIMARY KEY AUTOINCREMENT, value TEXT", "", True, True),
        ("id BIGINT PRIMARY KEY, value TEXT", "", False, False),
        ("id INT PRIMARY KEY, value TEXT", "", False, False),
        ("id INTEGER(8) PRIMARY KEY, value TEXT", "", False, False),
        ("id INTEGER, scope INTEGER, PRIMARY KEY(id, scope)", "", False, False),
        ("id INTEGER PRIMARY KEY, value TEXT", " WITHOUT ROWID", False, False),
        ("id INTEGER PRIMARY KEY DESC, value TEXT", "", False, False),
        ("id INTEGER, value TEXT, PRIMARY KEY(id DESC)", "", True, False),
        ("id INTEGER PRIMARY KEY, value TEXT DEFAULT 'WITHOUT ROWID PRIMARY KEY DESC'", "", True, False),
    ],
)
def test_sqlite_rowid_alias_is_a_distinct_fact_from_explicit_autoincrement(
    tmp_path: Path, declaration: str, suffix: str, is_rowid_alias: bool, is_autoincrement: bool
) -> None:
    path = tmp_path / "rowid-facts.sqlite3"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(f"CREATE TABLE example ({declaration}){suffix}")
    registry = UIState()
    conn = registry.add_connection(str(path), provider="base")
    try:
        warning = (
            pytest.warns(SAWarning, match="Could not instantiate type")
            if "INTEGER(8)" in declaration
            else nullcontext()
        )
        with warning:
            table = _tables(_workbench().inspect_connection(conn))["example"]
        column = next(column for column in table["columns"] if column["name"] == "id")
        assert column["is_rowid_alias"] is is_rowid_alias
        assert column["is_autoincrement"] is is_autoincrement
        assert all(not other["is_rowid_alias"] for other in table["columns"] if other["name"] != "id")
        assert table["row_count"] == 0
        with closing(sqlite3.connect(path)) as db, db:
            try:
                db.execute("INSERT INTO example DEFAULT VALUES")
            except sqlite3.IntegrityError:
                assert not is_rowid_alias
            else:
                assigned_id = db.execute("SELECT id FROM example").fetchone()[0]
                assert (assigned_id == 1) is is_rowid_alias
    finally:
        registry.close_connection(conn.conn_id)


def test_implicit_rowid_keeps_core_generator_overrides_while_explicit_autoincrement_is_readonly(tmp_path: Path) -> None:
    from sqlseed.config.models import ColumnConfig

    path = tmp_path / "rowid-rules.sqlite3"
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(
            "CREATE TABLE implicit_id(id INTEGER PRIMARY KEY,value TEXT);"
            "CREATE TABLE explicit_id(id INTEGER PRIMARY KEY AUTOINCREMENT,value TEXT);"
        )
    registry = UIState()
    conn = registry.add_connection(str(path), provider="base")
    try:
        tables = _tables(_workbench().inspect_connection(conn))
        implicit = tables["implicit_id"]["columns"][0]
        explicit = tables["explicit_id"]["columns"][0]
        assert implicit["is_rowid_alias"] and not implicit["is_autoincrement"]
        assert explicit["is_rowid_alias"] and explicit["is_autoincrement"]
        rules = [
            ColumnConfig(name="id", generator="integer", params={"min_value": 42, "max_value": 99}),
            ColumnConfig(name="value", generator="choice", params={"choices": ["written"]}),
        ]
        implicit_result = conn.orchestrator.fill_table("implicit_id", count=1, column_configs=rules, skip_ai=True)
        explicit_result = conn.orchestrator.fill_table("explicit_id", count=1, column_configs=rules, skip_ai=True)
        assert not implicit_result.errors and not explicit_result.errors
        with closing(sqlite3.connect(path)) as db, db:
            assert 42 <= db.execute("SELECT id FROM implicit_id").fetchone()[0] <= 99
            assert db.execute("SELECT id FROM explicit_id").fetchone()[0] == 1
    finally:
        registry.close_connection(conn.conn_id)
