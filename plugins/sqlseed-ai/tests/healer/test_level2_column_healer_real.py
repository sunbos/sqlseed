"""Real-LLM tests for Level2ColumnHealer.heal_column() (Spec 6.4 + 6.12).

Skipped when LM Studio is not available at ``http://localhost:1234``.
Uses a real SQLite database + real SchemaSnapshot to exercise the full
column-level heal path per Spec 6.1 (no mocks).
"""

from __future__ import annotations

import sqlite3

import pytest
from sqlseed_ai.healer.level2_column_healer import Level2ColumnHealer
from sqlseed_ai.validator.models import ConstraintType, ViolationReport
from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot


@pytest.fixture
def snapshot_with_products(tmp_path):
    """Build a real SQLite DB with a products table (CHECK price > 0)."""
    db_path = str(tmp_path / "test_l2.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, price REAL CHECK(price > 0))")
    conn.commit()
    conn.close()
    return SchemaSnapshot(db_path=db_path)


def _make_violation() -> ViolationReport:
    return ViolationReport(
        table="products",
        columns=["price"],
        constraint_type=ConstraintType.CHECK,
        severity="semantic_error",
        raw_expression="price > 0",
        message="CHECK constraint failed: price > 0",
    )


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


def test_level2_heal_column_real(llm_client, llm_model, snapshot_with_products):
    """Level2ColumnHealer.heal_column() returns a structured Level2Result.

    LLM output is non-deterministic — assert on structure, not content.
    """
    healer = Level2ColumnHealer(client=llm_client, model=llm_model)
    result = healer.heal_column(
        "products",
        "price",
        _make_violation(),
        _make_config(),
        snapshot_with_products,
    )

    assert result.column == "price"
    assert result.success in (True, False)
    assert result.elapsed_seconds >= 0
    assert result.prompt_tokens > 0
    if result.success:
        assert isinstance(result.config_patch, dict)
    else:
        assert result.error is not None or result.raw_response is not None
