from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from sqlseed import fill, preview

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(name="bench_db")
def create_bench_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "bench.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT, age INTEGER, created_at TEXT)")
    conn.close()
    return db_path


@pytest.mark.benchmark(group="fill")
def test_bench_fill_1k_rows(benchmark, bench_db) -> None:
    benchmark(fill, bench_db, table="users", count=1000, provider="base", clear_before=True)


@pytest.mark.benchmark(group="fill")
def test_bench_fill_10k_rows(benchmark, bench_db) -> None:
    benchmark(fill, bench_db, table="users", count=10000, provider="base", clear_before=True)


@pytest.mark.benchmark(group="fill")
def test_bench_preview_5_rows(benchmark, bench_db) -> None:
    benchmark(preview, bench_db, table="users", count=5, provider="base")
