"""Tests for builtin contract violations (Section 3.3)."""

from __future__ import annotations

from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
from sqlseed_ai.contracts.matrix import ContractResolver, ViolationKind


def test_builtin_violations_nonempty():
    assert len(BUILTIN_VIOLATIONS) >= 15


def test_integer_on_timestamp_crash():
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    v = resolver.check("integer", "TIMESTAMP", frozenset(), {})
    assert v is not None
    assert v.kind == ViolationKind.CRASH
    assert v.fix_strategy == "switch_generator"
    assert v.fix_params["target"] == "datetime"


def test_float_on_text_semantic_error():
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    v = resolver.check("float", "TEXT", frozenset(), {})
    assert v is not None
    assert v.kind == ViolationKind.SEMANTIC_ERROR


def test_choice_on_unique_code_like_column():
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    # pool_size >= row_count so expand_pool predicate is False;
    # only upgrade_to_template (code-like name) should match.
    v = resolver.check(
        "choice", "TEXT", frozenset({"UNIQUE"}), {"name": "order_code", "row_count": 100, "pool_size": 200}
    )
    assert v is not None
    assert v.fix_strategy == "upgrade_to_template"


def test_random_float_on_integer_column():
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    v = resolver.check("random_float", "INTEGER", frozenset(), {})
    assert v is not None
    assert v.fix_strategy == "coerce_float_to_int"
