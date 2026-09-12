"""Shared product-price CHECK scenario for real healer integration tests."""

from __future__ import annotations

from sqlseed_ai.validator.models import ConstraintType, ViolationReport


def product_price_violation() -> ViolationReport:
    return ViolationReport(
        table="products",
        columns=["price"],
        constraint_type=ConstraintType.CHECK,
        severity="semantic_error",
        raw_expression="price > 0",
        message="CHECK constraint failed: price > 0",
    )


def product_price_config() -> dict:
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
