"""Tests for healer.diff_learner module."""

from __future__ import annotations

from sqlseed_ai.contracts.matrix import ContractViolation, ViolationKind
from sqlseed_ai.healer.diff_learner import FORBIDDEN_PERSIST_KEYS, DiffLearner
from sqlseed_ai.repair.models import AppliedFix


def _fix(strategy: str, after: dict) -> AppliedFix:
    return AppliedFix(
        table="t",
        columns=["col"],
        fix_strategy=strategy,
        before={"generator": "integer"},
        after=after,
        violation_kind="crash",
        success=True,
    )


def test_safe_fix_produces_contract():
    learner = DiffLearner(schema_hash="abc123")
    fix = _fix("switch_generator", {"generator": "datetime"})
    contract = learner.learn_from_fix(
        fix,
        generator="integer",
        column_type="TIMESTAMP",
        constraints=frozenset(),
    )
    assert contract is not None
    assert contract.kind == ViolationKind.CRASH
    assert contract.fix_strategy == "switch_generator"
    assert contract.source == "auto_learned"
    assert contract.schema_hash == "abc123"


def test_rce_fix_with_custom_function_rejected():
    """Defense 7: fix referencing custom_function must NOT be persisted."""
    learner = DiffLearner(schema_hash="abc123")
    fix = _fix(
        "apply_custom_function",
        {"custom_function": "lambda x: __import__('os').system(x)"},
    )
    contract = learner.learn_from_fix(
        fix,
        generator="string",
        column_type="TEXT",
        constraints=frozenset({"UNIQUE"}),
    )
    assert contract is None  # rejected


def test_rce_fix_with_eval_rejected():
    """Defense 7: fix referencing eval/exec must NOT be persisted."""
    learner = DiffLearner(schema_hash="abc123")
    fix = _fix("apply_expression", {"expression": "eval('1+1')"})
    contract = learner.learn_from_fix(
        fix,
        generator="string",
        column_type="TEXT",
        constraints=frozenset(),
    )
    assert contract is None


def test_failed_fix_not_learned():
    """Only successful fixes are learned (avoids learning broken patterns)."""
    learner = DiffLearner(schema_hash="abc123")
    fix = AppliedFix(
        table="t",
        columns=["col"],
        fix_strategy="switch_generator",
        before={"generator": "integer"},
        after={"generator": "datetime"},
        violation_kind="crash",
        success=False,  # failed
    )
    contract = learner.learn_from_fix(
        fix,
        generator="integer",
        column_type="TIMESTAMP",
        constraints=frozenset(),
    )
    assert contract is None


def test_forbidden_keys_blacklist_complete():
    """Defense 7: blacklist covers all known RCE vectors."""
    expected = {
        "custom_function",
        "eval",
        "exec",
        "__import__",
        "compile",
        "globals",
        "locals",
        "getattr",
        "setattr",
    }
    assert expected.issubset(FORBIDDEN_PERSIST_KEYS)


def test_contract_is_contract_violation_instance():
    """Verify the returned contract is a proper ContractViolation instance."""
    learner = DiffLearner(schema_hash="abc123")
    fix = _fix("switch_generator", {"generator": "datetime"})
    contract = learner.learn_from_fix(
        fix,
        generator="integer",
        column_type="TIMESTAMP",
        constraints=frozenset(),
    )
    assert isinstance(contract, ContractViolation)
