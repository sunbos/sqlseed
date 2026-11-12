"""Unsupported seeds fail before clearing real SQLite data without narrowing compatibility."""

from __future__ import annotations

import json
import random
from decimal import Decimal
from fractions import Fraction
from typing import TYPE_CHECKING, Any

import pytest

from sqlseed import FillOptions, connect, fill, fill_from_config, preview
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


_INVALID_SEEDS = [[], {}, (1,), object(), Decimal(2), Fraction(2)]
_COMPATIBILITY_SEEDS = [None, 0, -2, 10**50, True, 2.5, "seed", b"seed", bytearray(b"seed")]


def _require_unsupported_seed(seed: Any) -> str:
    try:
        random.Random(seed)
    except TypeError as error:
        return str(error)
    return pytest.skip("This Python version accepts the seed; it must not be rejected by preflight")


def _prepare(path: Path) -> None:
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE items(id INTEGER PRIMARY KEY, value INTEGER NOT NULL);"
            "INSERT INTO items VALUES(777,888);"
            "CREATE TABLE other(id INTEGER PRIMARY KEY, value INTEGER NOT NULL);"
            "INSERT INTO other VALUES(999,111);"
        )


def _rows(path: Path, table: str = "items") -> list[tuple[int, int]]:
    with sqlite_connection(path) as db:
        if table == "items":
            return db.execute("SELECT * FROM items ORDER BY id").fetchall()
        return db.execute("SELECT * FROM other ORDER BY id").fetchall()


def _preserved(path: Path, before: bytes) -> None:
    assert path.read_bytes() == before
    assert _rows(path) == [(777, 888)]
    assert _rows(path, "other") == [(999, 111)]
    with sqlite_connection(path, timeout=0) as db:
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        db.execute("BEGIN EXCLUSIVE")
        db.rollback()


def _failed(result: Any, expected_error: str) -> None:
    assert result.count == 0
    assert result.batch_count == 0
    assert result.errors == [expected_error]


def _success(result: Any) -> None:
    assert result.count == 3
    assert result.batch_count == 1
    assert not result.errors


def _invoke(entry: str, path: Path, config: Path, seed: Any) -> list[Any]:
    if entry == "config":
        return fill_from_config(str(config), seed=seed, clear_before=True)
    if entry == "options":
        return [
            fill(
                str(path),
                table="items",
                count=3,
                options=FillOptions(provider="base", seed=seed, clear_before=True),
            )
        ]
    return [fill(str(path), table="items", count=3, provider="base", seed=seed, clear_before=True)]


@pytest.mark.parametrize("entry", ["fill", "options", "config"])
@pytest.mark.parametrize("seed", _INVALID_SEEDS)
def test_unsupported_seed_preserves_rows_and_allows_retry(tmp_path: Path, entry: str, seed: Any) -> None:
    expected_error = _require_unsupported_seed(seed)
    path = tmp_path / "seed.db"
    _prepare(path)
    config = tmp_path / "seed.json"
    config.write_text(
        json.dumps(
            {
                "db_path": str(path),
                "provider": "base",
                "tables": [{"name": "items", "count": 3}, {"name": "other", "count": 3}],
            }
        ),
        encoding="utf-8",
    )
    before, config_before = path.read_bytes(), config.read_bytes()
    state = random.getstate()
    results = _invoke(entry, path, config, seed)
    assert random.getstate() == state
    assert len(results) == (2 if entry == "config" else 1)
    for result in results:
        _failed(result, expected_error)
    _preserved(path, before)
    for result in _invoke(entry, path, config, 42):
        _success(result)
    assert len(_rows(path)) == 3
    assert len(_rows(path, "other")) == (3 if entry == "config" else 1)
    assert config.read_bytes() == config_before


@pytest.mark.parametrize("entry", ["fill_table", "fill"])
@pytest.mark.parametrize("seed", _INVALID_SEEDS)
def test_connected_unsupported_seed_preserves_rows_and_same_connection_retry(
    tmp_path: Path, entry: str, seed: Any
) -> None:
    expected_error = _require_unsupported_seed(seed)
    path = tmp_path / "connected.db"
    _prepare(path)
    before = path.read_bytes()
    with connect(str(path), provider="base") as orch:
        method = getattr(orch, entry)
        state = random.getstate()
        _failed(method("items", count=3, seed=seed, clear_before=True, skip_ai=True), expected_error)
        assert random.getstate() == state
        _preserved(path, before)
        _success(method("items", count=3, seed=42, clear_before=True, skip_ai=True))
        assert len(_rows(path)) == 3


@pytest.mark.parametrize("connected", [False, True])
@pytest.mark.parametrize("seed", _INVALID_SEEDS)
def test_preview_retains_type_error_and_database(tmp_path: Path, connected: bool, seed: Any) -> None:
    expected_error = _require_unsupported_seed(seed)
    path = tmp_path / "preview.db"
    _prepare(path)
    before = path.read_bytes()
    state = random.getstate()
    if connected:
        with connect(str(path), provider="base") as orch:
            with pytest.raises(TypeError) as caught:
                orch.preview_table("items", count=3, seed=seed)
            assert str(caught.value) == expected_error
            _preserved(path, before)
            assert len(orch.preview_table("items", count=3, seed=42)) == 3
    else:
        with pytest.raises(TypeError) as caught:
            preview(str(path), table="items", count=3, seed=seed, provider="base")
        assert str(caught.value) == expected_error
        _preserved(path, before)
        assert len(preview(str(path), table="items", count=3, seed=42, provider="base")) == 3
    _preserved(path, before)
    assert random.getstate() == state


@pytest.mark.parametrize("provider", ["base", "faker"])
@pytest.mark.parametrize("seed", _COMPATIBILITY_SEEDS)
def test_compatible_seeds_keep_generation_and_reproducibility(tmp_path: Path, provider: str, seed: Any) -> None:
    path = tmp_path / "compatible.db"
    _prepare(path)
    before = path.read_bytes()
    state = random.getstate()
    # Random(bytearray(...)) rejects the seed on Python 3.10, although calling
    # Random().seed(...) directly accepts it. Follow the constructor used by
    # generation and verify both runtime outcomes without skipping coverage.
    constructor_error = None
    try:
        random.Random(seed)
    except TypeError as error:
        constructor_error = str(error)

    first = fill(str(path), table="items", count=3, provider=provider, seed=seed, clear_before=True)
    if constructor_error is not None:
        _failed(first, constructor_error)
        _preserved(path, before)
        _success(fill(str(path), table="items", count=3, provider=provider, seed=42, clear_before=True))
        assert len(_rows(path)) == 3
        assert _rows(path, "other") == [(999, 111)]
        assert random.getstate() == state
        return

    _success(first)
    rows = _rows(path)
    second = fill(str(path), table="items", count=3, provider=provider, seed=seed, clear_before=True)
    _success(second)
    assert len(rows) == len(_rows(path)) == 3
    if seed is not None:
        assert rows == _rows(path)
    assert random.getstate() == state
    assert _rows(path, "other") == [(999, 111)]


def test_explicit_seed_overrides_options_without_validating_unused_seed(tmp_path: Path) -> None:
    path = tmp_path / "override.db"
    _prepare(path)
    bad_options = FillOptions(provider="base", seed=[], clear_before=True)
    _success(fill(str(path), table="items", count=3, options=bad_options, seed=42))
    before = path.read_bytes()
    good_options = FillOptions(provider="base", seed=42, clear_before=True)
    _failed(
        fill(str(path), table="items", count=3, options=good_options, seed=[]),
        _require_unsupported_seed([]),
    )
    assert path.read_bytes() == before
