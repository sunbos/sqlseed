"""Real-LLM tests for HealOrchestrator 4-level flow (Spec 6.4 + 6.12).

Skipped when LM Studio is not available at ``http://localhost:1234``.
Exercises the full 4-level degradation path with real LLM calls per
Spec 6.1 (no mocks). A stub validator is used — it is NOT an LLM
component (Spec 6.1 forbids LLM mocks only); the validator is a
deterministic rule engine, stubbed here to isolate the heal flow.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest
from sqlseed_ai.config import AIConfig
from sqlseed_ai.healer.context_detector import ContextWindowDetector
from sqlseed_ai.healer.degrader import ProgressiveDegrader
from sqlseed_ai.healer.failure_classifier import FailureClassifier
from sqlseed_ai.healer.level1_subgraph_healer import Level1SubgraphHealer
from sqlseed_ai.healer.level2_column_healer import Level2ColumnHealer
from sqlseed_ai.healer.level3_compact_healer import Level3CompactHealer
from sqlseed_ai.healer.models import SubgraphTask
from sqlseed_ai.healer.orchestrator import HealOrchestrator
from sqlseed_ai.validator.models import ConstraintType, ValidationResult, ViolationReport
from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot


class _StubValidator:
    """Minimal validator stub — NOT an LLM mock.

    The validator is a deterministic rule engine (Spec 6.1 forbids LLM
    mocks only). Stubbing it here isolates the 4-level heal orchestration
    flow for testing.
    """

    def __init__(self, always_violate: bool = False) -> None:
        self._always_violate = always_violate

    def validate(
        self,
        config: dict[str, Any],
        snapshot: Any,
        fill_error: Exception | None = None,
        dialect: str = "sqlite",
        batch: list[dict[str, Any]] | None = None,
    ) -> ValidationResult:
        if self._always_violate:
            return ValidationResult(violations=[_make_violation()], column_groups=[])
        return ValidationResult(violations=[], column_groups=[])


def _make_violation() -> ViolationReport:
    return ViolationReport(
        table="products",
        columns=["price"],
        constraint_type=ConstraintType.CHECK,
        severity="semantic_error",
        raw_expression="price > 0",
        message="CHECK constraint failed: price > 0",
    )


def _make_task() -> SubgraphTask:
    return SubgraphTask(task_id="t1", tables=["products"])


def _make_config() -> dict:
    return {
        "tables": [
            {
                "name": "products",
                "columns": [
                    {"name": "id", "generator": "integer"},
                    {
                        "name": "price",
                        "generator": "random_float",
                        "params": {"min_value": -10, "max_value": 100},
                    },
                ],
            }
        ]
    }


@pytest.fixture
def snapshot_with_products(tmp_path):
    """Build a real SQLite DB with a products table (CHECK price > 0)."""
    db_path = str(tmp_path / "test_orch.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE products (id INTEGER PRIMARY KEY, price REAL CHECK(price > 0))"
    )
    conn.commit()
    conn.close()
    return SchemaSnapshot(db_path=db_path)


def _build_orchestrator(
    llm_client: Any,
    llm_model: str,
    snapshot: SchemaSnapshot,
    *,
    always_violate: bool = False,
) -> HealOrchestrator:
    ai_config = AIConfig(max_context_tokens=8192)
    return HealOrchestrator(
        snapshot=snapshot,
        context_detector=ContextWindowDetector(ai_config, model=llm_model),
        failure_classifier=FailureClassifier(),
        level1=Level1SubgraphHealer(client=llm_client, model=llm_model),
        level2=Level2ColumnHealer(client=llm_client, model=llm_model),
        level3=Level3CompactHealer(client=llm_client, model=llm_model),
        degrader=ProgressiveDegrader(snapshot=snapshot),
        validator=_StubValidator(always_violate=always_violate),
        max_rounds=1,
        time_budget_seconds=120,
    )


def test_orchestrator_heal_flow_real(llm_client, llm_model, snapshot_with_products):
    """HealOrchestrator.heal() returns a HealResult with attempt records.

    Exercises the real 4-level flow. LLM output is non-deterministic —
    assert on structure, not on exact success/failure.
    """
    orch = _build_orchestrator(
        llm_client, llm_model, snapshot_with_products, always_violate=False
    )
    result = orch.heal(_make_task(), [_make_violation()], _make_config())

    assert isinstance(result.success, bool)
    assert result.level_used >= 0
    assert len(result.attempts) >= 1
    assert result.total_attempts >= 1
    assert result.total_elapsed >= 0


def test_orchestrator_degrade_on_persistent_violations_real(
    llm_client, llm_model, snapshot_with_products
):
    """HealOrchestrator degrades to Level 4 when violations persist.

    With ``always_violate=True`` and ``max_rounds=1``, the orchestrator
    must exhaust its retry budget and degrade via ProgressiveDegrader.
    """
    orch = _build_orchestrator(
        llm_client, llm_model, snapshot_with_products, always_violate=True
    )
    result = orch.heal(_make_task(), [_make_violation()], _make_config())

    assert result.success is False
    assert result.level_used == 4
    assert len(result.attempts) >= 1
