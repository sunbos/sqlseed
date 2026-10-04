"""Reject missing SQLite targets before consulting caches or an HTTP model."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import pytest

from sqlseed._utils.sql_safe import quote_identifier
from sqlseed.config.models import TableConfig
from sqlseed.core.orchestrator import DataOrchestrator
from tests.sqlite_helpers import sqlite_connection

try:
    from sqlseed_ai.refiner import AISuggestionFailedError
except ModuleNotFoundError as exc:
    if exc.name != "sqlseed_ai":
        raise
    pytest.skip("sqlseed-ai is not installed", allow_module_level=True)

from .test_refiner_json_recovery import _completion_server, _refiner

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("cached", [False, True])
def test_missing_target_rejected_without_http_cache_or_database_changes(
    tmp_path: Path, streaming: bool, cached: bool
) -> None:
    database = tmp_path / "existing.db"
    with sqlite_connection(database) as db:
        db.execute("CREATE TABLE preserved(value INTEGER)")
        db.execute("INSERT INTO preserved VALUES (17)")
        db.execute("PRAGMA user_version=3")
    before = database.read_bytes()
    requests: list[dict[str, object]] = []
    with _completion_server([('{"wrong": "shape"}', "stop")], requests) as base_url:
        refiner = _refiner(database, base_url)
        if cached:
            # An old cache with the former empty-column hash must not authorize a missing target.
            refiner._cache_successful_config(
                "missing_table", {"name": "missing_table", "columns": []}, hashlib.sha256(b"").hexdigest()[:16]
            )
        cache_dir = tmp_path / "cache"
        cache_before = {path.name: path.read_bytes() for path in cache_dir.glob("*")}
        generate = refiner.generate_and_refine_streaming if streaming else refiner.generate_and_refine
        with pytest.raises(ValueError, match="Table 'missing_table' does not exist or has no columns"):
            generate("missing_table", max_retries=0)

    assert not requests
    assert {path.name: path.read_bytes() for path in cache_dir.glob("*")} == cache_before
    assert database.read_bytes() == before
    with sqlite_connection(database) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("preserved",)]
        assert db.execute("SELECT value FROM preserved").fetchall() == [(17,)]
        assert db.execute("PRAGMA user_version").fetchone() == (3,)


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    "actual_name,requested_name,suggested_name,column_name",
    [
        ("events", "events", "events", "value"),
        ("MixedCase", "mixedcase", "MIXEDCASE", "value"),
        ('Order/"Items', 'order/"items', 'Order/"Items', "value"),
        (".events", ".events", ".events", ".value"),
        (":events", ":events", ":events", ":value"),
    ],
)
def test_existing_empty_table_keeps_sqlite_identifier_resolution(
    tmp_path: Path, streaming: bool, actual_name: str, requested_name: str, suggested_name: str, column_name: str
) -> None:
    database = tmp_path / "empty.db"
    with sqlite_connection(database) as db:
        quoted_column = quote_identifier(column_name)
        db.execute(
            f"CREATE TABLE {quote_identifier(actual_name)}({quoted_column} INTEGER NOT NULL CHECK({quoted_column}=7))"
        )
        if actual_name.startswith((".", ":")):
            db.execute("CREATE TABLE events(value INTEGER)")
            db.execute("INSERT INTO events VALUES (17)")
    before = database.read_bytes()
    config = {
        "name": suggested_name,
        "columns": [{"name": column_name, "generator": "integer", "params": {"min_value": 7, "max_value": 7}}],
    }
    requests: list[dict[str, object]] = []
    with _completion_server([(json.dumps(config), "stop")], requests) as base_url:
        refiner = _refiner(database, base_url)
        generate = refiner.generate_and_refine_streaming if streaming else refiner.generate_and_refine
        result = generate(requested_name, max_retries=0, no_cache=True)

    assert len(requests) == 1
    table = TableConfig.model_validate(result)
    assert table.name == suggested_name
    assert table.columns[0].name == column_name
    assert table.columns[0].params == {"min_value": 7, "max_value": 7}
    assert database.read_bytes() == before
    assert not (tmp_path / "cache").exists()
    with sqlite_connection(database) as db:
        assert db.execute(f"SELECT COUNT(*) FROM {quote_identifier(actual_name)}").fetchone() == (0,)


@pytest.mark.parametrize("streaming", [False, True])
def test_existing_target_valid_cache_still_avoids_http(tmp_path: Path, streaming: bool) -> None:
    """Reuse a matching target cache without an HTTP request or database mutation."""
    database = tmp_path / "cached.db"
    with sqlite_connection(database) as db:
        db.execute("CREATE TABLE events(value INTEGER)")
    config = {"name": "EVENTS", "columns": [{"name": "value", "generator": "integer"}]}
    before = database.read_bytes()
    requests: list[dict[str, object]] = []
    with _completion_server([('{"wrong": "shape"}', "stop")], requests) as base_url:
        refiner = _refiner(database, base_url)
        with DataOrchestrator(str(database)) as orch:
            schema_hash = refiner._compute_schema_hash(orch, "events")
        refiner._cache_successful_config("events", config, schema_hash)
        cache_file = refiner._cache_path("events")
        cache_before = cache_file.read_bytes()
        generate = refiner.generate_and_refine_streaming if streaming else refiner.generate_and_refine
        result = generate("events", max_retries=0)

    assert result == config
    assert not requests
    assert cache_file.read_bytes() == cache_before
    assert database.read_bytes() == before


@pytest.mark.parametrize("streaming", [False, True])
def test_column_set_changes_invalidate_cache_without_confusing_delimiters(tmp_path: Path, streaming: bool) -> None:
    """A renamed column set needs fresh rules, while column order alone keeps the cache."""
    database = tmp_path / "column-boundaries.db"
    column_sets = [("a|b", "c"), ("a", "b|c"), ("b|c", "a")]
    configs = [
        {
            "name": "events",
            "columns": [
                {"name": name, "generator": "integer", "params": {"min_value": 7, "max_value": 7}} for name in names
            ],
        }
        for names in column_sets[:2]
    ]
    requests: list[dict[str, object]] = []
    hashes: list[str] = []
    with _completion_server([(json.dumps(config), "stop") for config in configs], requests) as base_url:
        refiner = _refiner(database, base_url)
        generate = refiner.generate_and_refine_streaming if streaming else refiner.generate_and_refine
        for index, names in enumerate(column_sets):
            with sqlite_connection(database) as db:
                db.execute("DROP TABLE IF EXISTS events")
                columns = ", ".join(
                    f"{quote_identifier(name)} INTEGER NOT NULL CHECK({quote_identifier(name)}=7)" for name in names
                )
                db.execute(f"CREATE TABLE events({columns})")
            before = database.read_bytes()
            result = generate("events", max_retries=0)
            assert result == configs[min(index, 1)]
            assert len(requests) == min(index + 1, 2)
            entry = json.loads(refiner._cache_path("events").read_text(encoding="utf-8"))
            hashes.append(entry["_meta"]["schema_hash"])
            assert database.read_bytes() == before

    assert hashes[0] != hashes[1]
    assert hashes[1] == hashes[2]


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("old_column_name", ["value", '["value"]'])
def test_legacy_delimiter_hash_is_not_reused_for_new_cache_encoding(
    tmp_path: Path, streaming: bool, old_column_name: str
) -> None:
    """Reject old hashes even when an old column name spells the new JSON payload."""
    database = tmp_path / "legacy-hash.db"
    with sqlite_connection(database) as db:
        db.execute("CREATE TABLE events(value INTEGER NOT NULL CHECK(value=7))")
    before = database.read_bytes()
    correct = {
        "name": "events",
        "columns": [{"name": "value", "generator": "integer", "params": {"min_value": 7, "max_value": 7}}],
    }
    stale = {
        "name": "events",
        "columns": [{"name": old_column_name, "generator": "integer", "params": {"min_value": 99, "max_value": 99}}],
    }
    old_hash = hashlib.sha256(old_column_name.encode("utf-8")).hexdigest()[:16]
    requests: list[dict[str, object]] = []
    with _completion_server([(json.dumps(correct), "stop")], requests) as base_url:
        refiner = _refiner(database, base_url)
        refiner._cache_successful_config("events", stale, old_hash)
        generate = refiner.generate_and_refine_streaming if streaming else refiner.generate_and_refine
        result = generate("events", max_retries=0)

    assert result == correct
    assert len(requests) == 1
    entry = json.loads(refiner._cache_path("events").read_text(encoding="utf-8"))
    assert entry["_meta"]["schema_hash"] != old_hash
    assert entry["config"] == correct
    assert database.read_bytes() == before


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("target,other", [("events", "other"), ("Ävents", "ävents")])
def test_other_target_gets_retry_feedback_without_changing_database(
    tmp_path: Path, streaming: bool, target: str, other: str
) -> None:
    database = tmp_path / "targets.db"
    with sqlite_connection(database) as db:
        for name in (target, other):
            db.execute(f"CREATE TABLE {quote_identifier(name)}(value INTEGER NOT NULL CHECK(value=7))")
    before = database.read_bytes()
    columns = [{"name": "value", "generator": "integer", "params": {"min_value": 7, "max_value": 7}}]
    wrong, correct = {"name": other, "columns": columns}, {"name": target, "columns": columns}
    requests: list[dict[str, object]] = []
    with _completion_server([(json.dumps(wrong), "stop"), (json.dumps(correct), "stop")], requests) as base_url:
        refiner = _refiner(database, base_url)
        generate = refiner.generate_and_refine_streaming if streaming else refiner.generate_and_refine
        result = generate(target, max_retries=1, no_cache=True)

    assert result == correct
    assert len(requests) == 2
    messages = requests[1]["messages"]
    assert isinstance(messages, list)
    assert "table_mismatch" in messages[-1]["content"]
    assert target in messages[-1]["content"]
    assert other in messages[-1]["content"]
    assert database.read_bytes() == before
    assert not (tmp_path / "cache").exists()


@pytest.mark.parametrize("streaming", [False, True])
def test_other_target_exhausts_budget_without_caching_it(tmp_path: Path, streaming: bool) -> None:
    database = tmp_path / "targets.db"
    with sqlite_connection(database) as db:
        db.execute("CREATE TABLE events(value INTEGER)")
        db.execute("CREATE TABLE other(value INTEGER)")
    before = database.read_bytes()
    wrong = {"name": "other", "columns": [{"name": "value", "generator": "integer"}]}
    requests: list[dict[str, object]] = []
    with _completion_server([(json.dumps(wrong), "stop")], requests) as base_url:
        refiner = _refiner(database, base_url)
        generate = refiner.generate_and_refine_streaming if streaming else refiner.generate_and_refine
        with pytest.raises(AISuggestionFailedError, match="requested table 'events'"):
            generate("events", max_retries=0)

    assert len(requests) == 1
    assert database.read_bytes() == before
    assert not (tmp_path / "cache").exists()


@pytest.mark.parametrize("streaming", [False, True])
def test_other_target_cache_is_ignored_and_replaced_only_by_valid_suggestion(tmp_path: Path, streaming: bool) -> None:
    """Replace a mismatched target cache only after validating fresh rules for the requested table."""
    database = tmp_path / "targets.db"
    with sqlite_connection(database) as db:
        db.execute("CREATE TABLE events(value INTEGER)")
        db.execute("CREATE TABLE other(value INTEGER)")
    before = database.read_bytes()
    columns = [{"name": "value", "generator": "integer", "params": {"min_value": 7, "max_value": 7}}]
    wrong, correct = {"name": "other", "columns": columns}, {"name": "events", "columns": columns}
    requests: list[dict[str, object]] = []
    with _completion_server([(json.dumps(correct), "stop")], requests) as base_url:
        refiner = _refiner(database, base_url)
        with DataOrchestrator(str(database)) as orch:
            schema_hash = refiner._compute_schema_hash(orch, "events")
        refiner._cache_successful_config("events", wrong, schema_hash)
        generate = refiner.generate_and_refine_streaming if streaming else refiner.generate_and_refine
        result = generate("events", max_retries=0)

    assert result == correct
    assert len(requests) == 1
    assert refiner.get_cached_config("events") == correct
    assert database.read_bytes() == before


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    "entry",
    [
        {"_meta": None, "config": {"name": "events"}},
        {"_meta": [], "config": {"name": "events"}},
        {"_meta": "invalid", "config": {"name": "events"}},
        {"_meta": {}, "config": None},
        {"_meta": {}, "config": []},
        {"_meta": {}, "config": "invalid"},
        {"_meta": {}},
    ],
)
def test_malformed_cache_is_a_miss_then_replaced_after_real_validation(
    tmp_path: Path, streaming: bool, entry: dict[str, object]
) -> None:
    database = tmp_path / "cache-shape.db"
    with sqlite_connection(database) as db:
        db.execute("CREATE TABLE events(value INTEGER NOT NULL CHECK(value=7))")
    before = database.read_bytes()
    correct = {
        "name": "events",
        "columns": [{"name": "value", "generator": "integer", "params": {"min_value": 7, "max_value": 7}}],
    }
    requests: list[dict[str, object]] = []
    with _completion_server([(json.dumps(correct), "stop")], requests) as base_url:
        refiner = _refiner(database, base_url)
        cache_file = refiner._cache_path("events")
        cache_file.parent.mkdir()
        cache_file.write_text(json.dumps(entry), encoding="utf-8")
        assert refiner.get_cached_config("events") is None
        generate = refiner.generate_and_refine_streaming if streaming else refiner.generate_and_refine
        result = generate("events", max_retries=0)

    assert result == correct
    assert len(requests) == 1
    assert refiner.get_cached_config("events") == correct
    assert json.loads(cache_file.read_text(encoding="utf-8"))["_meta"]["cache_format"] == 2
    assert database.read_bytes() == before
