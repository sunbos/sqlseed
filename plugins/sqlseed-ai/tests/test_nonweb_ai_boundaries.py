"""Real SQLite regressions for cache, downgrade and schema identity boundaries."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytest.importorskip("sqlseed_ai")

from sqlseed_ai.analyzer import SchemaAnalyzer
from sqlseed_ai.config import AIBackend, AIConfig
from sqlseed_ai.healer.degrader import ProgressiveDegrader
from sqlseed_ai.healer.models import DegradeReason
from sqlseed_ai.healer.orchestrator import HealOrchestrator
from sqlseed_ai.refiner import AiConfigRefiner
from sqlseed_ai.validator.models import ConstraintType, ViolationReport
from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot


def refiner_for(path: Path, cache: Path, table: str, monkeypatch: pytest.MonkeyPatch) -> AiConfigRefiner:
    analyzer = SchemaAnalyzer(AIConfig(backend=AIBackend.LM_STUDIO, model="fixed-test-model"))
    monkeypatch.setattr(
        analyzer,
        "call_llm",
        lambda *args, **kwargs: {
            "name": table,
            "count": 1,
            "columns": [{"name": "value", "generator": "integer", "params": {"min_value": 7, "max_value": 7}}],
        },
    )
    return AiConfigRefiner(analyzer, str(path), cache_dir=str(cache))


@pytest.mark.parametrize("absolute", [False, True])
def test_refiner_cache_keeps_quoted_table_names_inside_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, absolute: bool
) -> None:
    path, cache = tmp_path / "test.db", tmp_path / "cache"
    table = str(tmp_path / "outside") if absolute else "../outside"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE "' + table + '"(value INTEGER NOT NULL)')
    refiner = refiner_for(path, cache, table, monkeypatch)
    result = refiner.generate_and_refine(table, max_retries=0, use_compact=True)
    assert not (tmp_path / "outside.json").exists()
    files = list(cache.glob("*.json"))
    assert len(files) == 1
    assert refiner.get_cached_config(table) == result
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute('SELECT count(*) FROM "' + table + '"').fetchone()[0] == 0


def test_refiner_refuses_unsafe_legacy_cache_but_reads_safe_legacy_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    refiner = refiner_for(tmp_path / "unused.db", cache, "users", monkeypatch)
    entry = {"_meta": {"schema_hash": "old"}, "config": {"name": "users", "columns": []}}
    (tmp_path / "outside.json").write_text(json.dumps(entry))
    assert refiner.get_cached_config("../outside", "old") is None
    (cache / "users.json").write_text(json.dumps(entry))
    assert refiner.get_cached_config("users", "old") == entry["config"]
    assert refiner.get_cached_config("users", "different") is None
    (cache / "linked.json").symlink_to(tmp_path / "outside.json")
    assert refiner.get_cached_config("linked", "old") is None


def test_refiner_first_cache_miss_accepts_long_table_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path, cache = tmp_path / "test.db", tmp_path / "cache"
    cache.mkdir()
    table = "x" * 300
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE "' + table + '"(value INTEGER NOT NULL)')
    refiner = refiner_for(path, cache, table, monkeypatch)
    result = refiner.generate_and_refine(table, max_retries=0, use_compact=True)
    assert result["name"] == table
    assert refiner.get_cached_config(table) == result
    assert len(list(cache.glob("*.json"))) == 1
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute('SELECT count(*) FROM "' + table + '"').fetchone()[0] == 0


@pytest.mark.parametrize("existing", [False, True])
def test_no_cache_disables_both_cache_read_and_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    path, cache = tmp_path / "test.db", tmp_path / "cache"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE users(value INTEGER NOT NULL)")
    refiner = refiner_for(path, cache, "users", monkeypatch)
    if existing:
        refiner.generate_and_refine("users", max_retries=0, use_compact=True)
        cache_file = next(cache.glob("*.json"))
        entry = json.loads(cache_file.read_text())
        entry["config"]["columns"][0]["params"] = {"min_value": 99, "max_value": 99}
        cache_file.write_text(json.dumps(entry))
        before = cache_file.read_bytes()
    result = refiner.generate_and_refine("users", max_retries=0, no_cache=True, use_compact=True)
    assert result["columns"][0]["params"]["min_value"] == 7
    if existing:
        assert cache_file.read_bytes() == before
    else:
        assert not cache.exists()


def test_real_qualified_failure_restores_only_its_table_before_degradation(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript("CREATE TABLE users(phone TEXT CHECK(length(phone)=11)); CREATE TABLE contacts(phone TEXT);")
    snapshot = SchemaSnapshot(db_path=str(path))
    original = {
        "tables": [
            {
                "name": "users",
                "columns": [{"name": "phone", "generator": "pattern", "params": {"pattern": "[0-9]{11}"}}],
            },
            {
                "name": "contacts",
                "columns": [{"name": "phone", "generator": "pattern", "params": {"pattern": "[0-9]{8}"}}],
            },
        ]
    }
    current = deepcopy(original)
    for table in current["tables"]:
        table["columns"][0] = {"name": "phone", "generator": "phone", "params": {}}
    violations = [
        ViolationReport(
            table="users", columns=["phone"], constraint_type=ConstraintType.CHECK, severity="semantic_error"
        )
    ]
    failed = HealOrchestrator._collect_failed_columns(violations)
    restored = HealOrchestrator._restore_failed_columns(current, original, failed)
    result, _ = ProgressiveDegrader(snapshot).degrade(
        restored, {name: DegradeReason.LLM_FAILURE for name in failed}, []
    )
    assert result["tables"][0]["columns"][0]["params"] == {"pattern": "[0-9]{11}"}
    assert result["tables"][0]["columns"][0]["_degraded"] is True
    assert result["tables"][1]["columns"][0] == current["tables"][1]["columns"][0]
    assert current["tables"][0]["columns"][0]["generator"] == "phone"


@pytest.mark.parametrize(
    "before, after",
    [
        ("value TEXT", "value TEXT NOT NULL"),
        ("value TEXT DEFAULT 'pending'", "value TEXT DEFAULT 'ready'"),
        (
            "source INTEGER, value INTEGER GENERATED ALWAYS AS (source + 1) STORED",
            "source INTEGER, value INTEGER GENERATED ALWAYS AS (source + 2) STORED",
        ),
    ],
)
def test_snapshot_detects_column_semantic_drift(tmp_path: Path, before: str, after: str) -> None:
    path = tmp_path / "test.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(f"CREATE TABLE sample({before})")
    snapshot = SchemaSnapshot(db_path=str(path))
    assert snapshot.validate_against_current(db_path=str(path))
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("DROP TABLE sample")
        db.execute(f"CREATE TABLE sample({after})")
    assert not snapshot.validate_against_current(db_path=str(path))
    assert snapshot.schema_hash != SchemaSnapshot(db_path=str(path)).schema_hash
