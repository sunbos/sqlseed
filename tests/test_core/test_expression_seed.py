"""Generation seeds also govern random functions in derived expressions."""

from __future__ import annotations

import random
import sqlite3
from typing import TYPE_CHECKING, Any

import pytest

from sqlseed.core.expression import ExpressionEngine
from sqlseed.core.orchestrator import DataOrchestrator
from tests.assertions import assert_empty
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


_COLUMNS = {
    "source": {"generator": "integer", "params": {"min_value": 1, "max_value": 1}},
    "sample_int": {"derive_from": "source", "expression": "random_int(0, 1000000000)"},
    "sample_float": {"derive_from": "source", "expression": "random_float(0, 1)"},
    "sample_choice": {"derive_from": "source", "expression": "random_choice(['A', 'B', 'C'])"},
}


def _generate_rows(db_path: Path, seed: int, mode: str) -> list[dict[str, Any]]:
    with sqlite_connection(db_path) as conn:
        conn.execute("CREATE TABLE samples (source INTEGER, sample_int INTEGER, sample_float REAL, sample_choice TEXT)")
    with DataOrchestrator(str(db_path), provider_name="base") as orch:
        if mode == "preview":
            rows = orch.preview_table("samples", count=6, seed=seed, columns=_COLUMNS)
            with sqlite_connection(db_path) as conn:
                assert conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 0
            return rows
        result = orch.fill_table("samples", count=6, seed=seed, columns=_COLUMNS, batch_size=2, skip_ai=True)
        assert_empty(result.errors, list)
        assert result.count == 6
    with sqlite_connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT * FROM samples ORDER BY rowid")]


@pytest.mark.parametrize("mode", ["preview", "fill"])
@pytest.mark.parametrize("seed", [0, 42])
def test_derived_random_functions_repeat_across_new_databases(tmp_path: Path, mode: str, seed: int) -> None:
    global_state = random.getstate()
    try:
        first = _generate_rows(tmp_path / "first.db", seed, mode)
        second = _generate_rows(tmp_path / "second.db", seed, mode)
        different_seed = _generate_rows(tmp_path / "different.db", seed + 1, mode)
        assert first == second
        assert first != different_seed
    finally:
        random.setstate(global_state)


@pytest.mark.parametrize("mode", ["preview", "fill"])
def test_seeded_generation_does_not_advance_global_random(tmp_path: Path, mode: str) -> None:
    global_state = random.getstate()
    try:
        _generate_rows(tmp_path / "isolated.db", 42, mode)
        assert random.getstate() == global_state
    finally:
        random.setstate(global_state)


def test_seeded_engine_keeps_one_local_sequence_and_argument_conversions() -> None:
    engine = ExpressionEngine(seed=17)
    reference = random.Random(17)
    for _ in range(4):
        assert engine.evaluate("random_int('1', '1000000')", {}) == reference.randint(1, 1000000)
        assert engine.evaluate("random_float('1.5', '2.5')", {}) == reference.uniform(1.5, 2.5)
        assert engine.evaluate("random_choice(value)", {"value": ("A", "B", "C")}) == reference.choice(["A", "B", "C"])


def test_unseeded_engine_keeps_global_random_compatibility() -> None:
    global_state = random.getstate()
    reference = random.Random()
    reference.setstate(global_state)
    try:
        engine = ExpressionEngine()
        assert engine.evaluate("random_int(1, 1000000)", {}) == reference.randint(1, 1000000)
        assert engine.evaluate("random_float(1.5, 2.5)", {}) == reference.uniform(1.5, 2.5)
        assert engine.evaluate("random_choice(value)", {"value": ("A", "B", "C")}) == reference.choice(["A", "B", "C"])
        assert random.getstate() == reference.getstate()
    finally:
        random.setstate(global_state)
