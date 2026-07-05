"""Tests for Layer 1 sparse contract matrix (Section 3.2)."""

from __future__ import annotations

from datetime import datetime

from sqlseed_ai.contracts.matrix import (
    ContractResolver,
    ContractViolation,
    ViolationKind,
)


def test_contract_violation_to_dict_round_trip():
    v = ContractViolation(
        generator="integer",
        column_type="TIMESTAMP",
        constraints=frozenset(),
        kind=ViolationKind.CRASH,
        fix_strategy="switch_generator",
        fix_params={"target": "datetime"},
        source="builtin",
    )
    d = v.to_dict()
    assert d["generator"] == "integer"
    assert d["column_type"] == "TIMESTAMP"
    assert d["constraints"] == []
    assert d["kind"] == "crash"
    assert d["fix_strategy"] == "switch_generator"
    assert d["fix_params"] == {"target": "datetime"}

    restored = ContractViolation.from_dict(d)
    assert restored.generator == v.generator
    assert restored.column_type == v.column_type
    assert restored.constraints == v.constraints
    assert restored.kind == v.kind
    assert restored.fix_strategy == v.fix_strategy
    assert restored.fix_params == v.fix_params
    assert restored.predicate is None  # predicate excluded from serialization


def test_contract_violation_hash_eq_dedup():
    v1 = ContractViolation(
        generator="float",
        column_type="TEXT",
        constraints=frozenset(),
        kind=ViolationKind.SEMANTIC_ERROR,
        fix_strategy="switch_generator",
        fix_params={"target": "string"},
        source="builtin",
    )
    v2 = ContractViolation(
        generator="float",
        column_type="TEXT",
        constraints=frozenset(),
        kind=ViolationKind.SEMANTIC_ERROR,
        fix_strategy="switch_generator",
        fix_params={"target": "string"},
        source="auto_learned",
        learned_at=datetime.now(),  # differs but not part of identity
    )
    assert v1 == v2
    assert hash(v1) == hash(v2)
    s = {v1, v2}
    assert len(s) == 1  # dedup by identity fields


def test_resolver_returns_none_for_compatible_combo():
    resolver = ContractResolver(builtin=set(), learned=set())
    result = resolver.check(
        generator="integer",
        column_type="INTEGER",
        constraints=frozenset(),
        config={},
    )
    assert result is None


def test_resolver_exact_match_beats_wildcard():
    exact = ContractViolation(
        generator="integer",
        column_type="TIMESTAMP",
        constraints=frozenset(),
        kind=ViolationKind.CRASH,
        fix_strategy="switch_generator",
        fix_params={"target": "datetime"},
    )
    wildcard = ContractViolation(
        generator="integer",
        column_type="ANY",
        constraints=frozenset(),
        kind=ViolationKind.SEMANTIC_ERROR,
        fix_strategy="normalize_params",
    )
    resolver = ContractResolver(builtin={exact, wildcard}, learned=set())
    result = resolver.check(
        generator="integer",
        column_type="TIMESTAMP",
        constraints=frozenset(),
        config={},
    )
    assert result is exact  # specificity 1 beats specificity 3


def test_resolver_learned_beats_builtin_on_tie():
    builtin_v = ContractViolation(
        generator="choice",
        column_type="ANY",
        constraints=frozenset({"UNIQUE"}),
        kind=ViolationKind.UNIQUE_UNSATISFIABLE,
        fix_strategy="expand_pool",
    )
    learned_v = ContractViolation(
        generator="choice",
        column_type="ANY",
        constraints=frozenset({"UNIQUE"}),
        kind=ViolationKind.UNIQUE_UNSATISFIABLE,
        fix_strategy="upgrade_to_template",
        source="auto_learned",
    )
    resolver = ContractResolver(builtin={builtin_v}, learned={learned_v})
    result = resolver.check(
        generator="choice",
        column_type="TEXT",
        constraints=frozenset({"UNIQUE"}),
        config={},
    )
    assert result is learned_v


def test_resolver_predicate_false_skips_violation():
    v = ContractViolation(
        generator="choice",
        column_type="ANY",
        constraints=frozenset({"UNIQUE"}),
        kind=ViolationKind.CONDITIONAL,
        fix_strategy="expand_pool",
        predicate=lambda cfg: cfg.get("row_count", 0) > cfg.get("pool_size", 0),
    )
    resolver = ContractResolver(builtin={v}, learned=set())
    # predicate False (pool_size >= row_count) → no violation
    assert resolver.check("choice", "TEXT", frozenset({"UNIQUE"}), {"row_count": 10, "pool_size": 100}) is None
    # predicate True → violation returned
    assert resolver.check("choice", "TEXT", frozenset({"UNIQUE"}), {"row_count": 100, "pool_size": 10}) is v
