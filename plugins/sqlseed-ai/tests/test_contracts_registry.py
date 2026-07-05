"""Tests for LearnedContractsRegistry (Section 3.4, Defenses 1+7)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlseed_ai.contracts.matrix import ContractViolation, ViolationKind
from sqlseed_ai.contracts.registry import (
    FORBIDDEN_PERSIST_KEYS,
    SAFE_FIX_STRATEGIES,
    LearnedContractsRegistry,
)

if TYPE_CHECKING:
    from pathlib import Path


def _make_v(**kwargs):
    defaults = dict(
        generator="float",
        column_type="TEXT",
        constraints=frozenset(),
        kind=ViolationKind.SEMANTIC_ERROR,
        fix_strategy="switch_generator",
        fix_params={"target": "string"},
        source="auto_learned",
    )
    defaults.update(kwargs)
    return ContractViolation(**defaults)


def test_add_persists_to_json(tmp_path: Path):
    path = tmp_path / "learned.json"
    reg = LearnedContractsRegistry(path=path)
    v = _make_v(schema_hash="abc123")
    assert reg.add(v) is True
    assert reg.size() == 1
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["contracts"]) == 1
    assert data["contracts"][0]["generator"] == "float"


def test_add_refuses_forbidden_persist_keys(tmp_path: Path):
    reg = LearnedContractsRegistry(path=tmp_path / "learned.json")
    v = _make_v(fix_params={"custom_function": "evil()"})
    assert reg.add(v) is False
    assert reg.size() == 0


def test_add_refuses_non_whitelist_strategy(tmp_path: Path):
    reg = LearnedContractsRegistry(path=tmp_path / "learned.json")
    v = _make_v(fix_strategy="execute_arbitrary_code")
    assert reg.add(v) is False
    assert reg.size() == 0


def test_filter_by_schema_hash(tmp_path: Path):
    reg = LearnedContractsRegistry(path=tmp_path / "learned.json")
    reg.add(_make_v(schema_hash="hash_a"))
    reg.add(_make_v(schema_hash="hash_b"))
    filtered = reg.filter_by_schema_hash("hash_a")
    assert len(filtered) == 1


def test_load_handles_corruption_gracefully(tmp_path: Path):
    path = tmp_path / "learned.json"
    path.write_text("{not valid json", encoding="utf-8")
    reg = LearnedContractsRegistry(path=path)
    assert reg.size() == 0  # corrupted → empty registry, no crash


def test_forbidden_persist_keys_includes_critical_dangers():
    for key in ("custom_function", "expression", "code", "eval", "exec", "lambda"):
        assert key in FORBIDDEN_PERSIST_KEYS


def test_safe_fix_strategies_includes_core_strategies():
    for s in (
        "switch_generator",
        "upgrade_to_template",
        "coerce_float_to_int",
        "fix_self_reference",
        "isolate_date_ranges",
    ):
        assert s in SAFE_FIX_STRATEGIES


# --- Phase 5 Task 5.1: save()/load() API with atomic save + Defense 7 re-check ---


def _contract_for_save(generator="integer", col_type="TIMESTAMP", source="auto_learned") -> ContractViolation:
    return ContractViolation(
        generator=generator,
        column_type=col_type,
        constraints=frozenset(),
        kind=ViolationKind.CRASH,
        fix_strategy="switch_generator",
        fix_params={"target": "datetime"},
        source=source,
        schema_hash="abc123",
    )


def test_save_and_load_roundtrip(tmp_path: Path):
    """Saved contracts can be loaded back via load()."""
    reg = LearnedContractsRegistry(path=tmp_path / "learned.json")
    c = _contract_for_save()
    reg.save([c])
    loaded = reg.load()
    assert len(loaded) == 1
    assert loaded[0].generator == "integer"
    assert loaded[0].schema_hash == "abc123"


def test_load_empty_file_returns_empty_list(tmp_path: Path):
    """Missing or empty file = empty list (no crash)."""
    reg = LearnedContractsRegistry(path=tmp_path / "nonexistent.json")
    assert reg.load() == []


def test_load_filter_by_schema_hash(tmp_path: Path):
    """Defense 8: only contracts matching the schema_hash are loaded."""
    reg = LearnedContractsRegistry(path=tmp_path / "learned.json")
    c1 = _contract_for_save()
    c2 = ContractViolation(
        generator="string",
        column_type="TEXT",
        constraints=frozenset(),
        kind=ViolationKind.SEMANTIC_ERROR,
        fix_strategy="normalize_params",
        fix_params={},
        source="auto_learned",
        schema_hash="different_hash",
    )
    reg.save([c1, c2])
    loaded = reg.load(schema_hash="abc123")
    assert len(loaded) == 1
    assert loaded[0].schema_hash == "abc123"


def test_atomic_save_uses_temp_file(tmp_path: Path):
    """Defense 1: save is atomic (temp file + rename)."""
    reg = LearnedContractsRegistry(path=tmp_path / "learned.json")
    reg.save([_contract_for_save()])
    assert (tmp_path / "learned.json").exists()
    temp_files = list(tmp_path.glob("learned.json.*.tmp"))
    assert temp_files == []


def test_load_rejects_tampered_rce_entries(tmp_path: Path):
    """Defense 7 re-check: tampered entries with forbidden keys are dropped on load."""
    reg = LearnedContractsRegistry(path=tmp_path / "learned.json")
    tampered = [
        {
            "generator": "string",
            "column_type": "TEXT",
            "constraints": [],
            "kind": "crash",
            "fix_strategy": "apply_custom_function",  # not in safe whitelist
            "fix_params": {"custom_function": "lambda x: __import__('os').system(x)"},
            "source": "auto_learned",
            "learned_at": None,
            "schema_hash": "abc123",
        }
    ]
    (tmp_path / "learned.json").write_text(json.dumps(tampered), encoding="utf-8")
    loaded = reg.load()
    assert loaded == []
