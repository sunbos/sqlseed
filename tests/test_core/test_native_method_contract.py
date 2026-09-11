"""Native-only column configuration is an executable source, not an inference hint."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest
from faker import Faker

from sqlseed import ColumnConfig
from sqlseed._utils.progress import NullProgressBackend
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.generators._protocol import ConfigurationError

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "column,definition", [("label", "TEXT"), ("native_text", "TEXT NOT NULL"), ("label", "TEXT DEFAULT 'db-default'")]
)
def test_native_only_configuration_matches_real_faker(
    tmp_path: Path,
    column: str,
    definition: str,
) -> None:
    path = tmp_path / "native.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(f"CREATE TABLE items(id INTEGER PRIMARY KEY,{column} {definition})")
    oracle = Faker("en_US")
    oracle.seed_instance(42)
    expected = [oracle.lexify(text="??") for _ in range(6)]
    config = ColumnConfig(name=column, faker_method="lexify", native_params={"text": "??"})
    with DataOrchestrator(str(path), provider_name="faker", locale="en_US", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items", count=6, seed=42, column_configs=[config], skip_ai=True, progress=NullProgressBackend()
        )
        assert result.errors == [] and result.count == 6
    with closing(sqlite3.connect(path)) as db, db:
        assert [row[0] for row in db.execute(f"SELECT {column} FROM items ORDER BY id")] == expected


@pytest.mark.parametrize("generator", [None, "string"])
def test_native_method_remains_active_for_all_unique_rows(tmp_path: Path, generator: str | None) -> None:
    path = tmp_path / "unique_native.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY,label TEXT NOT NULL UNIQUE)")
    oracle = Faker("en_US")
    oracle.seed_instance(42)
    expected: list[str] = []
    while len(expected) < 15:
        value = oracle.lexify(text="?")
        if value not in expected:
            expected.append(value)
    config = ColumnConfig(name="label", generator=generator, faker_method="lexify", native_params={"text": "?"})
    with DataOrchestrator(str(path), provider_name="faker", locale="en_US", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items",
            count=15,
            batch_size=3,
            seed=42,
            column_configs=[config],
            skip_ai=True,
            progress=NullProgressBackend(),
        )
        assert result.errors == [] and result.count == 15
    with closing(sqlite3.connect(path)) as db, db:
        assert [row[0] for row in db.execute("SELECT label FROM items ORDER BY id")] == expected


@pytest.mark.parametrize("generator", [None, "string"])
def test_unknown_native_method_fails_instead_of_silently_generating(
    tmp_path: Path,
    generator: str | None,
) -> None:
    path = tmp_path / "unknown_native.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE items(label TEXT)")
    config = ColumnConfig(name="label", generator=generator, faker_method="does_not_exist_sqlseed")
    with (
        DataOrchestrator(str(path), provider_name="faker", optimize_pragma=False) as orch,
        pytest.raises(ConfigurationError, match="does_not_exist_sqlseed"),
    ):
        orch.fill_table("items", count=1, column_configs=[config], skip_ai=True, progress=NullProgressBackend())
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0


def test_no_native_configuration_keeps_database_default(tmp_path: Path) -> None:
    path = tmp_path / "default.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY,label TEXT DEFAULT 'db-default')")
    with DataOrchestrator(str(path), provider_name="faker", optimize_pragma=False) as orch:
        result = orch.fill_table("items", count=2, skip_ai=True, progress=NullProgressBackend())
        assert result.errors == [] and result.count == 2
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute("SELECT label FROM items").fetchall() == [("db-default",), ("db-default",)]


def test_other_provider_native_hint_keeps_explicit_generator_fallback(tmp_path: Path) -> None:
    path = tmp_path / "fallback.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE items(value INTEGER NOT NULL CHECK(value=7))")
    config = ColumnConfig(
        name="value",
        generator="integer",
        params={"min_value": 7, "max_value": 7},
        mimesis_method="person.not_a_faker_method",
    )
    with DataOrchestrator(str(path), provider_name="faker", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items", count=2, column_configs=[config], skip_ai=True, progress=NullProgressBackend()
        )
        assert result.errors == [] and result.count == 2
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute("SELECT value FROM items").fetchall() == [(7,), (7,)]


def test_native_primary_key_retains_bounded_domain_and_unique_checks(tmp_path: Path) -> None:
    path = tmp_path / "bounded_native.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY CHECK(id BETWEEN 1 AND 2))")
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            db.execute("INSERT INTO items VALUES(3)")
    config = ColumnConfig(
        name="id",
        generator="integer",
        faker_method="random_int",
        native_params={"min": 1, "max": 4},
        constraints={"min_value": 1, "max_value": 2},
    )
    with DataOrchestrator(str(path), provider_name="faker", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items", count=2, seed=42, column_configs=[config], skip_ai=True, progress=NullProgressBackend()
        )
        assert result.errors == [] and result.count == 2
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute("SELECT id FROM items ORDER BY id").fetchall() == [(1,), (2,)]


def test_inactive_native_hint_keeps_unique_fallback_adjustment(tmp_path: Path) -> None:
    path = tmp_path / "unique_fallback.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY)")
    config = ColumnConfig(
        name="id",
        generator="integer",
        params={"min_value": 1, "max_value": 1},
        mimesis_method="person.not_a_faker_method",
        constraints={"max_retries": 1},
    )
    with DataOrchestrator(str(path), provider_name="faker", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items",
            count=3,
            seed=42,
            batch_size=1,
            column_configs=[config],
            skip_ai=True,
            progress=NullProgressBackend(),
        )
        assert result.errors == [] and result.count == 3
    with closing(sqlite3.connect(path)) as db, db:
        rows = db.execute("SELECT id FROM items").fetchall()
        assert len(rows) == len(set(rows)) == 3
