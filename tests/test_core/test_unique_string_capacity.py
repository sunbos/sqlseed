"""UNIQUE string planning follows the provider's actual character domain."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest

from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.generators._protocol import ConfigurationError

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("column_type,count", [("INT8", 256), ("INT16", 65536)])
def test_sqlite_integer_type_names_do_not_imply_bit_capacity(tmp_path: Path, column_type: str, count: int) -> None:
    path = tmp_path / "integer_capacity.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(f"CREATE TABLE items(code {column_type} NOT NULL UNIQUE)")
        db.executemany("INSERT INTO items VALUES (?)", ((value,) for value in range(count)))
        assert db.execute("SELECT COUNT(DISTINCT code) FROM items").fetchone() == (count,)


@pytest.mark.parametrize("clear_before", [False, True])
def test_impossible_nonnullable_integer_request_is_rejected_before_generation(
    tmp_path: Path, clear_before: bool
) -> None:
    path = tmp_path / "bounded_integer_capacity.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE items(code INTEGER NOT NULL UNIQUE CHECK(code BETWEEN 10 AND 12))")
        db.execute("INSERT INTO items VALUES (10)")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        with pytest.raises(ConfigurationError):
            orch.fill_table(
                "items",
                count=4,
                seed=42,
                skip_ai=True,
                clear_before=clear_before,
                columns={"code": {"generator": "integer", "params": {"min_value": 10, "max_value": 12}}},
            )
        assert orch.query("SELECT code FROM items") == [{"code": 10}]


def test_nullable_integer_unique_can_generate_more_rows_than_nonnull_values(tmp_path: Path) -> None:
    path = tmp_path / "nullable_integer_capacity.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE items(code INTEGER UNIQUE CHECK(code BETWEEN 10 AND 12))")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items",
            count=8,
            seed=42,
            skip_ai=True,
            columns={"code": {"generator": "integer", "params": {"min_value": 10, "max_value": 12}, "null_ratio": 0.5}},
        )
        rows = orch.query("SELECT code FROM items")
        values = [row["code"] for row in rows if row["code"] is not None]
        assert result.count == 8
        assert result.errors == []
        assert len(values) == len(set(values))
        assert set(values) <= {10, 11, 12}
        assert any(row["code"] is None for row in rows)


@pytest.mark.parametrize("enrich", [False, True])
def test_valid_clear_reuses_integer_domain_and_resolves_self_fk_from_new_rows(tmp_path: Path, enrich: bool) -> None:
    path = tmp_path / "clear_integer_capacity.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "CREATE TABLE items(id INTEGER PRIMARY KEY, code INTEGER NOT NULL UNIQUE CHECK(code BETWEEN 10 AND 12), "
            "parent_id INTEGER REFERENCES items(id))"
        )
        db.execute("INSERT INTO items VALUES (9000, 10, NULL)")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items",
            count=3,
            seed=42,
            clear_before=True,
            enrich=enrich,
            skip_ai=True,
            columns={"code": {"generator": "integer", "params": {"min_value": 10, "max_value": 12}}},
        )
        rows = orch.query("SELECT id, code, parent_id FROM items")
        ids = {row["id"] for row in rows}
        assert result.errors == []
        assert result.count == 3
        assert {row["code"] for row in rows} == {10, 11, 12}
        assert 9000 not in ids
        assert all(row["parent_id"] is None or row["parent_id"] in ids for row in rows)
        assert any(row["parent_id"] is not None for row in rows)
        assert orch.query("PRAGMA foreign_key_check") == []


@pytest.mark.parametrize("charset", ["01", "000111"])
def test_small_custom_charset_generates_requested_unique_rows(tmp_path: Path, charset: str) -> None:
    path = tmp_path / "binary_codes.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE items(code TEXT NOT NULL UNIQUE)")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items",
            count=1000,
            seed=42,
            skip_ai=True,
            columns={"code": {"generator": "string", "params": {"charset": charset, "max_length": 1}}},
        )
        assert result.errors == []
        assert result.count == 1000
        rows = orch.query("SELECT code FROM items")
        assert len({row["code"] for row in rows}) == 1000
        assert all(set(row["code"]) <= {"0", "1"} for row in rows)


@pytest.mark.parametrize("count", [69, 70, 1000])
def test_supported_string_batch_fits_database_length_check(tmp_path: Path, count: int) -> None:
    path = tmp_path / "three_character_codes.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE items(code TEXT NOT NULL UNIQUE CHECK(LENGTH(code) <= 3))")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items",
            count=count,
            seed=42,
            skip_ai=True,
            columns={"code": {"generator": "string", "params": {"charset": "alphanumeric", "max_length": 3}}},
        )
        rows = orch.query("SELECT code FROM items")
        assert result.errors == []
        assert result.count == count
        assert len({row["code"] for row in rows}) == count
        assert all(len(row["code"]) <= 3 for row in rows)


def test_bounded_binary_strings_reject_exhausted_domain_before_clear(tmp_path: Path) -> None:
    path = tmp_path / "binary_capacity.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE items(code TEXT NOT NULL UNIQUE CHECK(LENGTH(code) BETWEEN 1 AND 2))")
        db.execute("INSERT INTO items VALUES ('0')")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        with pytest.raises(ConfigurationError):
            orch.fill_table(
                "items",
                count=7,
                seed=42,
                clear_before=True,
                skip_ai=True,
                columns={
                    "code": {"generator": "string", "params": {"charset": "01", "min_length": 1, "max_length": 2}}
                },
            )
        assert orch.query("SELECT code FROM items") == [{"code": "0"}]


@pytest.mark.parametrize("charset", ["01", "z"])
def test_nullable_bounded_strings_can_exceed_nonnull_capacity(tmp_path: Path, charset: str) -> None:
    path = tmp_path / "nullable_string_capacity.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE items(code TEXT UNIQUE CHECK(LENGTH(code) BETWEEN 1 AND 2))")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items",
            count=12,
            seed=42,
            skip_ai=True,
            columns={
                "code": {
                    "generator": "string",
                    "params": {"charset": charset, "min_length": 1, "max_length": 2},
                    "null_ratio": 0.5,
                }
            },
        )
        rows = orch.query("SELECT code FROM items")
        nonnull = [row["code"] for row in rows if row["code"] is not None]
        assert result.count == 12
        assert result.errors == []
        assert len(nonnull) == len(set(nonnull))
        assert all(1 <= len(value) <= 2 for value in nonnull)
        assert any(row["code"] is None for row in rows)


@pytest.mark.parametrize("charset,min_length,max_length,count", [("", 0, 0, 1), ("aaa", 1, 5, 5)])
def test_degenerate_charset_uses_existing_finite_length_domain(
    tmp_path: Path, charset: str, min_length: int, max_length: int, count: int
) -> None:
    path = tmp_path / "finite_codes.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            f"CREATE TABLE items(code TEXT NOT NULL UNIQUE CHECK(LENGTH(code) BETWEEN {min_length} AND {max_length}))"
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "items",
            count=count,
            seed=42,
            skip_ai=True,
            columns={
                "code": {
                    "generator": "string",
                    "params": {"charset": charset, "min_length": min_length, "max_length": max_length},
                }
            },
        )
        assert result.errors == []
        assert result.count == count
        assert sorted(row["code"] for row in orch.query("SELECT code FROM items")) == [
            "a" * length for length in range(min_length, max_length + 1)
        ]


@pytest.mark.parametrize("charset,count", [("", 1), ("aaa", 6)])
def test_degenerate_charset_insufficient_domain_is_explicit_and_keeps_rows(
    tmp_path: Path, charset: str, count: int
) -> None:
    path = tmp_path / "invalid_codes.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE items(code TEXT NOT NULL UNIQUE)")
        db.execute("INSERT INTO items VALUES('sentinel')")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        with pytest.raises(ConfigurationError, match=r"character.*UNIQUE"):
            orch.fill_table(
                "items",
                count=count,
                seed=42,
                skip_ai=True,
                columns={
                    "code": {"generator": "string", "params": {"charset": charset, "min_length": 1, "max_length": 5}}
                },
            )
        assert orch.query("SELECT code FROM items") == [{"code": "sentinel"}]
