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


def test_builtin_violations_include_phone_to_pattern_rule():
    """Rule #23: phone generator on phone-like column should be in BUILTIN_VIOLATIONS."""
    from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
    from sqlseed_ai.contracts.matrix import ContractResolver

    resolver = ContractResolver(set(BUILTIN_VIOLATIONS), set())
    v = resolver.check(
        generator="phone",
        column_type="TEXT",
        constraints=frozenset(),
        config={"name": "phone"},
    )
    assert v is not None
    assert v.fix_strategy == "upgrade_phone_to_pattern"


def test_builtin_violations_include_text_on_code_unique_rule():
    """Rule #25: text generator on UNIQUE code-like column should be in BUILTIN_VIOLATIONS."""
    from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
    from sqlseed_ai.contracts.matrix import ContractResolver

    resolver = ContractResolver(set(BUILTIN_VIOLATIONS), set())
    v = resolver.check(
        generator="text",
        column_type="TEXT",
        constraints=frozenset({"UNIQUE"}),
        config={"name": "product_code"},
    )
    assert v is not None
    assert v.fix_strategy == "downgrade_text_to_string"
