"""Invalid public row counts are rejected before clearing real SQLite data."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from sqlseed import FillOptions, connect, fill, fill_from_config, preview
from tests.assertions import assert_empty
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


_INVALID_COUNTS = [True, False, 1.5, 1.0, float("nan"), float("inf"), float("-inf"), "2", 0, -1]
_FILL_ENTRIES = ["fill", "options", "connected", "alias", "config"]


def _prepare_database(path: Path) -> None:
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE items(id INTEGER PRIMARY KEY); INSERT INTO items VALUES(777);"
            "CREATE TABLE other(id INTEGER PRIMARY KEY); INSERT INTO other VALUES(888);"
        )


def _check_preserved(path: Path, before: bytes) -> None:
    assert path.read_bytes() == before
    with sqlite_connection(path) as db:
        assert db.execute("SELECT id FROM items").fetchall() == [(777,)]
        assert db.execute("SELECT id FROM other").fetchall() == [(888,)]
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]


def _fill(entry: str, path: Path, config: Path, count: Any) -> None:
    if entry == "config":
        results = fill_from_config(str(config), count=count, clear_before=True, skip_ai=True)
    elif entry == "options":
        options = FillOptions(provider="base", clear_before=True, skip_ai=True)
        results = [fill(str(path), table="items", count=count, options=options)]
    elif entry in {"connected", "alias"}:
        with connect(str(path), provider="base") as orch:
            method = orch.fill_table if entry == "connected" else orch.fill
            results = [method("items", count=count, clear_before=True, skip_ai=True)]
    else:
        results = [fill(str(path), table="items", count=count, provider="base", clear_before=True, skip_ai=True)]
    assert all(result.count == 2 and not result.errors for result in results)


@pytest.mark.parametrize("entry", _FILL_ENTRIES)
@pytest.mark.parametrize("count", _INVALID_COUNTS)
def test_invalid_count_preserves_database_and_allows_valid_retry(tmp_path: Path, entry: str, count: Any) -> None:
    path = tmp_path / "counts.db"
    _prepare_database(path)
    config = tmp_path / "counts.json"
    config.write_text(
        json.dumps(
            {
                "db_path": str(path),
                "provider": "base",
                "tables": [{"name": "items", "count": 2}, {"name": "other", "count": 2}],
            }
        ),
        encoding="utf-8",
    )
    before, config_before = path.read_bytes(), config.read_bytes()
    with pytest.raises(ValueError, match="count must be a positive integer"):
        _fill(entry, path, config, count)
    _check_preserved(path, before)
    assert config.read_bytes() == config_before
    _fill(entry, path, config, 2)
    with sqlite_connection(path) as db:
        assert db.execute("SELECT id FROM items ORDER BY id").fetchall() == [(1,), (2,)]
        assert db.execute("SELECT id FROM other ORDER BY id").fetchall() == (
            [(1,), (2,)] if entry == "config" else [(888,)]
        )
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    assert config.read_bytes() == config_before


@pytest.mark.parametrize("entry", ["fill", "options", "connected", "alias"])
def test_none_count_is_invalid_outside_config_override(tmp_path: Path, entry: str) -> None:
    path = tmp_path / "none.db"
    _prepare_database(path)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="count must be a positive integer"):
        _fill(entry, path, tmp_path / "unused.json", None)
    _check_preserved(path, before)


def test_config_none_override_keeps_per_table_counts(tmp_path: Path) -> None:
    path = tmp_path / "configured.db"
    _prepare_database(path)
    config = tmp_path / "configured.json"
    config.write_text(
        json.dumps(
            {
                "db_path": str(path),
                "provider": "base",
                "tables": [{"name": "items", "count": 2}, {"name": "other", "count": 3}],
            }
        ),
        encoding="utf-8",
    )
    results = fill_from_config(str(config), count=None, clear_before=True, skip_ai=True)
    assert {result.table_name: result.count for result in results} == {"items": 2, "other": 3}
    assert all(not result.errors for result in results)
    with sqlite_connection(path) as db:
        assert db.execute("SELECT COUNT(*) FROM items").fetchone() == (2,)
        assert db.execute("SELECT COUNT(*) FROM other").fetchone() == (3,)
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]


@pytest.mark.parametrize("entry", ["preview", "connected"])
@pytest.mark.parametrize("count", [*_INVALID_COUNTS, None])
def test_preview_rejects_invalid_count_without_changing_data(tmp_path: Path, entry: str, count: Any) -> None:
    path = tmp_path / "preview.db"
    _prepare_database(path)
    before = path.read_bytes()
    if entry == "preview":
        with pytest.raises(ValueError, match="count must be a positive integer"):
            preview(str(path), table="items", count=count, provider="base")
        assert len(preview(str(path), table="items", count=2, provider="base")) == 2
    else:
        with connect(str(path), provider="base") as orch:
            with pytest.raises(ValueError, match="count must be a positive integer"):
                orch.preview_table("items", count=count)
            assert len(orch.preview_table("items", count=2)) == 2
    _check_preserved(path, before)


def test_empty_config_keeps_no_op_override_semantics(tmp_path: Path) -> None:
    path = tmp_path / "empty.db"
    _prepare_database(path)
    before = path.read_bytes()
    config = tmp_path / "empty.json"
    config.write_text(json.dumps({"db_path": str(path), "provider": "base", "tables": []}), encoding="utf-8")
    assert_empty(fill_from_config(str(config), count=float("nan"), clear_before=True, skip_ai=True), list)
    _check_preserved(path, before)
