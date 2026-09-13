"""Invalid model output is repairable; programming defects remain observable."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
from typing import TYPE_CHECKING

import pytest

from sqlseed.core.orchestrator import DataOrchestrator
from tests.assertions import assert_empty
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path

    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

pytest.importorskip("sqlseed_ai")


@pytest.mark.parametrize("generator", [[], {}, 42])
def test_invalid_generator_value_recovers_schema_rule(tmp_path: Path, generator: object) -> None:
    from sqlseed_ai.auto_heal.orchestrator import AutoHealOrchestrator
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

    path = tmp_path / "generated.db"
    with sqlite_connection(path) as connection:
        connection.execute("CREATE TABLE items(value INTEGER CHECK(value >= 1))")
    config = {"tables": [{"name": "items", "count": 2, "columns": [{"name": "value", "generator": generator}]}]}
    orchestrator = AutoHealOrchestrator(db_path=str(path), heal_orchestrator=None, validator=None)

    orchestrator._normalize_generated_columns(config, SchemaSnapshot(db_path=str(path)))

    column = config["tables"][0]["columns"][0]
    assert column["generator"] == "integer"
    assert column["params"]["min_value"] >= 1


@pytest.mark.parametrize("generator", [[], {}, "unregistered_generator"])
def test_unknown_generator_does_not_enter_numeric_range_rules(generator: object) -> None:
    from sqlseed_ai.contracts.matrix import ContractResolver
    from sqlseed_ai.validator.single_column import SingleColumnValidator

    validator = SingleColumnValidator(ContractResolver(set(), set()))
    column = {"name": "value", "generator": generator}
    schema = {
        "columns": [{"name": "value", "type": "INTEGER"}],
        "constraints": [{"type": "check", "columns": ["value"], "expression": "value >= 1"}],
    }

    violations = validator.validate({"name": "items", "columns": [column]}, schema, row_count=2)

    assert_empty(violations, list)
    assert column["generator"] is generator


@pytest.mark.parametrize(
    ("values", "expected_generator"),
    [([False, 1.0, Decimal("1"), Fraction(0)], "boolean"), ([[], {}], "integer")],
)
def test_boolean_enum_requires_numeric_values(values: list[object], expected_generator: str) -> None:
    from sqlseed_ai.repair.strategies import REPAIR_STRATEGIES
    from sqlseed_ai.validator.models import ConstraintType, ViolationReport

    column = {"name": "flag", "generator": "integer"}
    violation = ViolationReport(
        table="items",
        columns=["flag"],
        constraint_type=ConstraintType.CHECK,
        severity="semantic_error",
        fix_hint="coerce_to_boolean_enum",
        fix_params={"check_values": values},
    )

    result = REPAIR_STRATEGIES["coerce_to_boolean_enum"](column, violation, {})

    assert result["generator"] == expected_generator
    assert column == {"name": "flag", "generator": "integer"}


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError], ids=["rejected-input", "programming-error"])
def test_strategy_failure_does_not_commit_partial_changes(
    timestamp_snapshot: SchemaSnapshot, error_type: type[Exception]
) -> None:
    from sqlseed_ai.repair.executor import RepairExecutor
    from sqlseed_ai.validator.models import ConstraintType, ViolationReport

    config = {"tables": [{"name": "t", "columns": [{"name": "x", "generator": "integer", "params": {"min_value": 1}}]}]}
    original = deepcopy(config)
    failure = error_type("strategy failed")
    violation = ViolationReport(
        table="t", columns=["x"], constraint_type=ConstraintType.CHECK, severity="crash", fix_hint="custom"
    )

    def incomplete_repair(column, _violation, _context):
        column["params"]["min_value"] = -100
        raise failure

    executor = RepairExecutor({"custom": incomplete_repair})
    if error_type is ValueError:
        result = executor.repair(config, [violation], timestamp_snapshot)
        assert result.fix_count == 0
        assert_empty(result.applied_fixes, list)
        assert result.unfixable == [violation]
    else:
        with pytest.raises(RuntimeError) as caught:
            executor.repair(config, [violation], timestamp_snapshot)
        assert caught.value is failure
    assert config == original


def test_logging_programming_error_is_not_an_io_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlseed_ai.analyzer import SchemaAnalyzer, _caller
    from sqlseed_ai.config import AIConfig

    failure = KeyError("broken cache configuration lookup")

    def broken_cache(_category: str):
        raise failure

    monkeypatch.setattr(_caller, "get_cache_dir", broken_cache)
    analyzer = SchemaAnalyzer(AIConfig(model="test", log_llm_interactions=True))

    with pytest.raises(KeyError) as caught:
        analyzer._log_llm_interaction(messages=[], response="complete", model="test")
    assert caught.value is failure


def test_preview_programming_error_is_not_a_database_rejection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlseed_ai.analyzer import SchemaAnalyzer
    from sqlseed_ai.config import AIConfig
    from sqlseed_ai.refiner import AiConfigRefiner

    path = tmp_path / "preview.db"
    with sqlite_connection(path) as connection:
        connection.execute("CREATE TABLE items(value INTEGER)")
    refiner = AiConfigRefiner(SchemaAnalyzer(AIConfig()), str(path), cache_dir=str(tmp_path / "cache"))
    failure = KeyError("broken validation implementation")

    def broken_validation(_table, _rows):
        raise failure

    monkeypatch.setattr(refiner, "_validate_varchar_lengths", broken_validation)
    with DataOrchestrator(str(path)) as orchestrator, pytest.raises(KeyError) as caught:
        refiner._validate_preview_insert(orchestrator, "items", [{"value": 1}])
    assert caught.value is failure
    with sqlite_connection(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0
