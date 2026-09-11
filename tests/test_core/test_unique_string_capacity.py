"""UNIQUE string planning follows the provider's actual character domain."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.generators._protocol import ConfigurationError

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("charset", ["01", "000111"])
def test_small_custom_charset_generates_requested_unique_rows(tmp_path: Path, charset: str) -> None:
    path = tmp_path / "binary_codes.db"
    with sqlite3.connect(path) as db:
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


@pytest.mark.parametrize("charset,min_length,max_length,count", [("", 0, 0, 1), ("aaa", 1, 5, 5)])
def test_degenerate_charset_uses_existing_finite_length_domain(
    tmp_path: Path, charset: str, min_length: int, max_length: int, count: int
) -> None:
    path = tmp_path / "finite_codes.db"
    with sqlite3.connect(path) as db:
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
    with sqlite3.connect(path) as db:
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
