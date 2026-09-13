"""Exact length CHECKs preserve equality and same-column nullable guards."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from sqlseed.config.models import ColumnConfig
from sqlseed.core.check_adapt import CheckAdapter
from sqlseed.core.check_parser import CheckConstraintParser
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "expression",
    [
        "LENGTH(phone) = 11",
        "11 = LENGTH(phone)",
        "LENGTH(phone) == 11",
        "phone IS NULL OR LENGTH(phone) = 11",
        "LENGTH(phone) = 11 OR phone IS NULL",
        '("phone" IS NULL) OR (11 = LENGTH("phone"))',
    ],
)
def test_exact_length_matches_real_sqlite_check(tmp_path: Path, expression: str) -> None:
    path = tmp_path / "length.db"
    with sqlite_connection(path) as db:
        db.execute(f"CREATE TABLE contacts(phone TEXT CHECK({expression}))")
        db.execute("INSERT INTO contacts VALUES (NULL)")
        db.execute("INSERT INTO contacts VALUES (?)", ("1" * 11,))
        for value in ("1" * 10, "1" * 13):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute("INSERT INTO contacts VALUES (?)", (value,))
    parsed = CheckConstraintParser.parse("phone", expression)
    assert parsed is not None
    assert parsed.kind == "length_range"
    assert parsed.min_length == parsed.max_length == 11


@pytest.mark.parametrize(
    "expression",
    [
        "other IS NULL OR LENGTH(phone) = 11",
        "phone IS NOT NULL OR LENGTH(phone) = 11",
        "phone IS NULL OR LENGTH(other) = 11",
        "phone IS NULL OR LENGTH(phone) = 11 OR other = 1",
        "phone IS NULL OR LENGTH(phone) = other",
        "LENGTH(phone) = -1",
        "LENGTH(phone) = '11'",
    ],
)
def test_other_guards_and_noninteger_literals_are_not_reinterpreted(expression: str) -> None:
    assert CheckConstraintParser.parse("phone", expression) is None


def test_equality_and_inequality_remain_distinct() -> None:
    equal = CheckConstraintParser.parse("phone", "LENGTH(phone) = 11")
    minimum = CheckConstraintParser.parse("phone", "LENGTH(phone) >= 11")
    assert equal is not None
    assert equal.min_length == equal.max_length == 11
    assert minimum is not None
    assert minimum.min_length == 11
    assert minimum.max_length is None


def test_nullable_check_guard_does_not_override_not_null(tmp_path: Path) -> None:
    with sqlite_connection(tmp_path / "not-null.db") as db:
        db.execute("CREATE TABLE contacts(phone TEXT NOT NULL CHECK(phone IS NULL OR LENGTH(phone) = 11))")
        with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
            db.execute("INSERT INTO contacts VALUES (NULL)")
        db.execute("INSERT INTO contacts VALUES (?)", ("1" * 11,))


def test_nullable_length_equality_adapts_real_string_parameters() -> None:
    column = ColumnConfig(name="phone", generator="string", params={"min_length": 5, "max_length": 20})
    CheckAdapter().adapt_user_configs({"phone": column}, ["phone IS NULL OR LENGTH(phone) = 11"])
    assert column.params == {"min_length": 11, "max_length": 11}


def test_length_equality_merges_with_other_checks() -> None:
    parsed = CheckConstraintParser.parse_all("phone", ["LENGTH(phone) >= 5", "phone IS NULL OR LENGTH(phone) = 11"])
    assert parsed is not None
    assert parsed.min_length == parsed.max_length == 11
