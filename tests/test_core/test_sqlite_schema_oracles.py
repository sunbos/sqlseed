"""Native SQLite operations independently establish generation schema semantics."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest

from sqlseed import fill_from_config
from sqlseed._utils.progress import NullProgressBackend
from sqlseed.core.orchestrator import DataOrchestrator

if TYPE_CHECKING:
    from pathlib import Path


def test_ascii_aliases_resolve_to_the_existing_table_and_share_fk_state(tmp_path: Path) -> None:
    path = tmp_path / "aliases.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE parents(id INTEGER PRIMARY KEY AUTOINCREMENT);"
            "CREATE TABLE children(id INTEGER PRIMARY KEY,parent_id INTEGER NOT NULL REFERENCES PARENTS(id));"
            'INSERT INTO "PARENTS" DEFAULT VALUES;'
        )
        assert db.execute('SELECT id FROM "PaReNtS"').fetchall() == [(1,)]
        db.execute("DELETE FROM parents")
    config = tmp_path / "aliases.json"
    config.write_text(
        json.dumps(
            {
                "db_path": str(path),
                "provider": "base",
                "tables": [{"name": "CHILDREN", "count": 2}, {"name": "PARENTS", "count": 2}],
            }
        ),
        encoding="utf-8",
    )
    results = fill_from_config(str(config))
    assert all(not result.errors and result.count == 2 for result in results)
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        for spelling in ["pArEnTs", "PARENTS"]:
            result = orch.fill_table(spelling, count=1, skip_ai=True, progress=NullProgressBackend())
            assert result.errors == [] and result.count == 1
        assert orch.query("PRAGMA foreign_key_check") == []
        assert orch.get_row_count("parents") == 4


def test_aliases_preserve_self_fk_generation(tmp_path: Path) -> None:
    path = tmp_path / "self_alias.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE nodes(id INTEGER PRIMARY KEY AUTOINCREMENT,parent_id INTEGER REFERENCES NODES(id))")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table("nOdEs", count=10, seed=42, skip_ai=True, progress=NullProgressBackend())
        assert result.errors == [] and result.count == 10
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT COUNT(*) FROM nodes WHERE parent_id IS NOT NULL").fetchone()[0] > 0


def test_public_topological_order_preserves_aliases_then_fills_parents_first(tmp_path: Path) -> None:
    path = tmp_path / "ordered_aliases.db"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript(
            "CREATE TABLE parents(id INTEGER PRIMARY KEY);"
            "CREATE TABLE children(parent_id INTEGER NOT NULL REFERENCES parents(id));"
        )
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            db.execute("INSERT INTO children VALUES(1)")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        ordered = orch.get_topological_table_order(["children", "PARENTS"])
        assert ordered == ["PARENTS", "children"]
        for table in ordered:
            result = orch.fill_table(table, count=2, seed=42, skip_ai=True, progress=NullProgressBackend())
            assert result.errors == [] and result.count == 2
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM parents").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM children").fetchone()[0] == 2
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_public_topological_order_keeps_non_ascii_tables_distinct(tmp_path: Path) -> None:
    path = tmp_path / "unicode_order.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            'CREATE TABLE "Äpfel"(id INTEGER PRIMARY KEY);'
            'CREATE TABLE "äpfel"(id INTEGER PRIMARY KEY);'
            'CREATE TABLE children(parent_id INTEGER REFERENCES "Äpfel"(id));'
            'INSERT INTO "Äpfel" VALUES(1);INSERT INTO "äpfel" VALUES(2);'
        )
        assert db.execute('SELECT id FROM "Äpfel"').fetchall() == [(1,)]
        assert db.execute('SELECT id FROM "äpfel"').fetchall() == [(2,)]
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        ordered = orch.get_topological_table_order(["children", "äpfel", "Äpfel"])
        assert set(ordered) == {"children", "äpfel", "Äpfel"}
        assert ordered.index("Äpfel") < ordered.index("children")


def test_duplicate_aliases_in_config_are_rejected_before_clearing(tmp_path: Path) -> None:
    path = tmp_path / "duplicate_alias.db"
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE items(id INTEGER PRIMARY KEY);INSERT INTO items VALUES(777);")
    config = tmp_path / "duplicate_alias.json"
    config.write_text(
        json.dumps(
            {
                "db_path": str(path),
                "provider": "base",
                "tables": [{"name": "items", "count": 1}, {"name": "ITEMS", "count": 1}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate references"):
        fill_from_config(str(config), clear_before=True)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT id FROM items").fetchall() == [(777,)]


def test_sqlite_non_ascii_names_are_not_casefolded(tmp_path: Path) -> None:
    path = tmp_path / "unicode.db"
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE "Äpfel"(id INTEGER PRIMARY KEY)')
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            db.execute('SELECT * FROM "äpfel"')
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table("äpfel", count=1, skip_ai=True, progress=NullProgressBackend())
        assert result.count == 0 and "does not exist" in result.errors[0]
        assert orch.get_row_count("Äpfel") == 0


@pytest.mark.parametrize("members", ["kind", "kind,region"])
@pytest.mark.parametrize("archived", [0, 1])
def test_partial_unique_only_constrains_rows_selected_by_its_predicate(
    tmp_path: Path, members: str, archived: int
) -> None:
    path = tmp_path / "partial.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items(kind TEXT NOT NULL,region TEXT NOT NULL,archived INTEGER NOT NULL)")
        db.execute(f"CREATE UNIQUE INDEX uq_active ON items({members}) WHERE archived=0")
        db.execute("INSERT INTO items VALUES('same','zone',?)", (archived,))
        if archived:
            db.execute("INSERT INTO items VALUES('same','zone',?)", (archived,))
            assert db.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2
        else:
            with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
                db.execute("INSERT INTO items VALUES('same','zone',?)", (archived,))
        db.execute("DELETE FROM items")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items",
            count=2,
            batch_size=1,
            skip_ai=True,
            progress=NullProgressBackend(),
            columns={
                "kind": {"generator": "template", "params": {"template": "same"}},
                "region": {"generator": "template", "params": {"template": "zone"}},
                "archived": {"generator": "choice", "params": {"choices": [archived]}},
            },
        )
        assert result.count == (2 if archived else 1)
        assert orch.get_row_count("items") == result.count
        if archived:
            assert result.errors == []
        else:
            assert result.errors and "UNIQUE constraint failed" in result.errors[0]


@pytest.mark.parametrize(
    "definition", ["id INTEGER PRIMARY KEY) WITHOUT ROWID", "id INTEGER PRIMARY KEY DESC NOT NULL)"]
)
def test_non_rowid_integer_pk_requires_generated_values(tmp_path: Path, definition: str) -> None:
    path = tmp_path / "non_rowid.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items(" + definition)
        with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
            db.execute("INSERT INTO items DEFAULT VALUES")
        db.execute("INSERT INTO items VALUES(777)")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table("items", count=2, seed=42, skip_ai=True, progress=NullProgressBackend())
        assert result.errors == [] and result.count == 2
        rows = orch.query("SELECT id FROM items")
        assert len(rows) == 3 and {"id": 777} in rows
        assert all(row["id"] is not None for row in rows)


def test_descending_integer_pk_preserves_sqlite_nullable_semantics(tmp_path: Path) -> None:
    path = tmp_path / "nullable_desc.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY DESC)")
        db.execute("INSERT INTO items VALUES(NULL),(NULL)")
        assert db.execute("SELECT id FROM items").fetchall() == [(None,), (None,)]
        db.execute("DELETE FROM items")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        column = orch._db.get_column_info("items")[0]
        assert column.nullable
        result = orch.fill_table(
            "items",
            count=2,
            skip_ai=True,
            progress=NullProgressBackend(),
            columns={"id": {"generator": "integer", "null_ratio": 1.0}},
        )
        assert result.errors == [] and result.count == 2
        assert orch.query("SELECT id FROM items") == [{"id": None}, {"id": None}]
