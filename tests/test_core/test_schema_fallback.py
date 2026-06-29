"""Tests for schema-driven fallback generator."""
from __future__ import annotations

from sqlseed.core.schema_fallback import SchemaFallbackGenerator
from sqlseed.database._protocol import CheckConstraintInfo, ColumnInfo


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


def _make_check(name: str, table: str, columns: tuple[str, ...], expr: str) -> CheckConstraintInfo:
    return CheckConstraintInfo(name=name, table=table, columns=columns, expression=expr)


class TestCheckDrivenFallback:
    """Test fallback generation driven by CHECK constraints."""

    def test_check_in_clause_uses_choice(self) -> None:
        gen = SchemaFallbackGenerator()
        checks = [_make_check("chk1", "t1", ("status",), "status IN ('A', 'B', 'C')")]
        spec = gen.fallback_for_column(_make_col("status", "TEXT"), checks, [])
        assert spec is not None
        assert spec.generator_name == "choice"
        assert spec.params["choices"] == ["A", "B", "C"]

    def test_check_between_uses_integer_range(self) -> None:
        gen = SchemaFallbackGenerator()
        checks = [_make_check("chk1", "t1", ("level",), "level BETWEEN 1 AND 100")]
        spec = gen.fallback_for_column(_make_col("level", "INTEGER"), checks, [])
        assert spec is not None
        assert spec.generator_name == "integer"
        assert spec.params["min_value"] == 1.0
        assert spec.params["max_value"] == 100.0

    def test_check_ge_uses_integer_min(self) -> None:
        gen = SchemaFallbackGenerator()
        checks = [_make_check("chk1", "t1", ("count",), "count >= 0")]
        spec = gen.fallback_for_column(_make_col("count", "INTEGER"), checks, [])
        assert spec is not None
        assert spec.generator_name == "integer"
        assert spec.params["min_value"] == 0.0

    def test_check_length_between_constrains_string(self) -> None:
        gen = SchemaFallbackGenerator()
        checks = [_make_check("chk1", "t1", ("code",), "length(code) BETWEEN 3 AND 50")]
        # VARCHAR(100) but CHECK limits to 50
        spec = gen.fallback_for_column(_make_col("code", "VARCHAR(100)"), checks, [])
        assert spec is not None
        assert spec.generator_name == "string"
        assert spec.params["max_length"] == 50
        assert spec.params["min_length"] == 3

    def test_cross_column_check_falls_back_to_type(self) -> None:
        """Cross-column CHECK (sale_price >= cost_price) cannot be auto-resolved."""
        gen = SchemaFallbackGenerator()
        checks = [_make_check("chk1", "t1", ("sale_price", "cost_price"), "sale_price >= cost_price")]
        spec = gen.fallback_for_column(_make_col("sale_price", "REAL"), checks, [])
        assert spec is not None
        # Falls back to type-driven (float), not CHECK-driven
        assert spec.generator_name == "float"

    def test_unique_string_gets_min_length(self) -> None:
        """UNIQUE string columns get min_length=8 to reduce collisions."""
        gen = SchemaFallbackGenerator()
        spec = gen.fallback_for_column(
            _make_col("code", "VARCHAR(20)"), [], ["code"]
        )
        assert spec is not None
        assert spec.params.get("min_length") == 8
        assert spec.params.get("max_length") == 20
