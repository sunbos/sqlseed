"""Tests for schema-driven fallback generator."""
from __future__ import annotations

from sqlseed.core.schema_fallback import SchemaFallbackGenerator
from sqlseed.database._protocol import ColumnInfo


def _make_col(
    name: str,
    type_str: str,
    *,
    nullable: bool = True,
    is_pk: bool = False,
    is_autoincrement: bool = False,
    default: object = None,
    is_computed: bool = False,
) -> ColumnInfo:
    """Factory for ColumnInfo in tests.

    Note: ColumnInfo uses `type` (not `type_name`) and has no `length`
    field — length is parsed from the type string like 'VARCHAR(50)'.
    """
    return ColumnInfo(
        name=name,
        type=type_str,
        nullable=nullable,
        default=default,
        is_primary_key=is_pk,
        is_autoincrement=is_autoincrement,
        is_computed=is_computed,
    )


class TestTypeDrivenFallback:
    """Test fallback generation based on SQL type alone (no constraints)."""

    def test_integer_generates_int(self) -> None:
        gen = SchemaFallbackGenerator()
        spec = gen.fallback_for_column(_make_col("count", "INTEGER"), [], [])
        assert spec is not None
        assert spec.generator_name == "integer"

    def test_text_generates_string(self) -> None:
        gen = SchemaFallbackGenerator()
        spec = gen.fallback_for_column(_make_col("desc", "TEXT"), [], [])
        assert spec is not None
        assert spec.generator_name == "string"

    def test_varchar_generates_string_with_length_from_type(self) -> None:
        """Length parsed from 'VARCHAR(50)' type string."""
        gen = SchemaFallbackGenerator()
        spec = gen.fallback_for_column(_make_col("code", "VARCHAR(50)"), [], [])
        assert spec is not None
        assert spec.generator_name == "string"
        assert spec.params.get("max_length") == 50

    def test_real_generates_float(self) -> None:
        gen = SchemaFallbackGenerator()
        spec = gen.fallback_for_column(_make_col("price", "REAL"), [], [])
        assert spec is not None
        assert spec.generator_name == "float"

    def test_pk_autoincrement_returns_none(self) -> None:
        gen = SchemaFallbackGenerator()
        spec = gen.fallback_for_column(
            _make_col("id", "INTEGER", is_pk=True, is_autoincrement=True, nullable=False),
            [], []
        )
        assert spec is None

    def test_column_with_default_returns_none(self) -> None:
        gen = SchemaFallbackGenerator()
        spec = gen.fallback_for_column(
            _make_col("status", "TEXT", default="pending"), [], []
        )
        assert spec is None

    def test_computed_column_returns_none(self) -> None:
        gen = SchemaFallbackGenerator()
        spec = gen.fallback_for_column(
            _make_col("total", "REAL", is_computed=True), [], []
        )
        assert spec is None
