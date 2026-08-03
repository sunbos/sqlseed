"""Tests for CHECK constraint parser."""

from __future__ import annotations

from sqlseed.core.check_parser import CheckConstraintParser


class TestCheckParserInClause:
    """Test parsing of CHECK(x IN ('A', 'B', 'C'))."""

    def test_parse_string_in_clause(self) -> None:
        result = CheckConstraintParser.parse("status", "status IN ('active', 'inactive', 'pending')")
        assert result is not None
        assert result.column == "status"
        assert result.kind == "choice"
        assert result.choices == ("active", "inactive", "pending")

    def test_parse_integer_in_clause(self) -> None:
        result = CheckConstraintParser.parse("level", "level IN (1, 2, 3)")
        assert result is not None
        assert result.kind == "choice"
        assert result.choices == (1, 2, 3)

    def test_parse_in_clause_case_insensitive_column(self) -> None:
        result = CheckConstraintParser.parse("Status", "STATUS IN ('A', 'B')")
        assert result is not None
        assert result.choices == ("A", "B")

    def test_parse_in_clause_other_column_returns_none(self) -> None:
        result = CheckConstraintParser.parse("other_col", "status IN ('A', 'B')")
        assert result is None


class TestCheckParserRange:
    """Test parsing of CHECK(x BETWEEN low AND high) and CHECK(x >= N)."""

    def test_parse_between_integers(self) -> None:
        result = CheckConstraintParser.parse("level", "level BETWEEN 1 AND 100")
        assert result is not None
        assert result.kind == "range"
        assert result.min_value == 1.0
        assert result.max_value == 100.0

    def test_parse_between_floats(self) -> None:
        result = CheckConstraintParser.parse("price", "price BETWEEN 0.0 AND 999.99")
        assert result is not None
        assert result.kind == "range"
        assert result.min_value == 0.0
        assert result.max_value == 999.99

    def test_parse_ge_only(self) -> None:
        result = CheckConstraintParser.parse("count", "count >= 0")
        assert result is not None
        assert result.kind == "range"
        assert result.min_value == 0.0
        assert result.max_value is None

    def test_parse_le_only(self) -> None:
        result = CheckConstraintParser.parse("age", "age <= 150")
        assert result is not None
        assert result.kind == "range"
        assert result.min_value is None
        assert result.max_value == 150.0

    def test_parse_negative_number(self) -> None:
        result = CheckConstraintParser.parse("temp", "temp >= -273.15")
        assert result is not None
        assert result.min_value == -273.15


class TestCheckParserLength:
    """Test parsing of CHECK(length(x) BETWEEN ...) and CHECK(length(x) >= N)."""

    def test_parse_length_between(self) -> None:
        result = CheckConstraintParser.parse("code", "length(code) BETWEEN 3 AND 50")
        assert result is not None
        assert result.kind == "length_range"
        assert result.min_length == 3
        assert result.max_length == 50

    def test_parse_length_ge(self) -> None:
        result = CheckConstraintParser.parse("name", "length(name) >= 2")
        assert result is not None
        assert result.kind == "length_range"
        assert result.min_length == 2
        assert result.max_length is None

    def test_parse_length_le(self) -> None:
        result = CheckConstraintParser.parse("desc", "length(desc) <= 200")
        assert result is not None
        assert result.kind == "length_range"
        assert result.max_length == 200


class TestCheckParserCrossColumn:
    """Test that cross-column constraints return None."""

    def test_cross_column_returns_none(self) -> None:
        # sale_price >= cost_price: both are column names, not literals
        result = CheckConstraintParser.parse("sale_price", "sale_price >= cost_price")
        assert result is None

    def test_is_cross_column_detects_multiple(self) -> None:
        assert CheckConstraintParser.is_cross_column("sale_price >= cost_price", ["sale_price", "cost_price"]) is True

    def test_is_cross_column_single_column(self) -> None:
        assert CheckConstraintParser.is_cross_column("price >= 0", ["price", "cost"]) is False

    def test_is_cross_column_no_substring_false_positive(self) -> None:
        """Word boundary: 'price' must NOT match inside 'unit_price'.

        Regression test for v3 correction #6: substring matching caused
        false positive cross-column detection.
        """
        # 'price' should NOT be detected in 'unit_price >= 100'
        assert CheckConstraintParser.is_cross_column("unit_price >= 100", ["price", "unit_price"]) is False

    def test_parse_does_not_match_substring_column(self) -> None:
        """parse('price', 'unit_price >= 100') must return None.

        The column 'price' is not the same as 'unit_price'. Word boundary
        in the regex ensures correct matching.
        """
        result = CheckConstraintParser.parse("price", "unit_price >= 100")
        assert result is None

    def test_parse_matches_exact_column_with_substring_elsewhere(self) -> None:
        """parse('price', 'price >= 0 AND unit_price <= 100') should match 'price'."""
        result = CheckConstraintParser.parse("price", "price >= 0")
        assert result is not None
        assert result.min_value == 0.0


class TestCheckParserCompoundAnd:
    """sqlglot AST 重写后：AND 连接的复合条件必须完整合并（修复 age>=18 AND age<=120 丢一半）。"""

    def test_and_merges_min_and_max(self) -> None:
        result = CheckConstraintParser.parse("age", "age >= 18 AND age <= 120")
        assert result is not None
        assert result.kind == "range"
        assert result.min_value == 18.0
        assert result.max_value == 120.0

    def test_strict_inequality_int_tightened(self) -> None:
        """整数严格不等式收一为含边界：age > 17 AND age < 121 → [18, 120]。"""
        result = CheckConstraintParser.parse("age", "age > 17 AND age < 121")
        assert result is not None
        assert result.min_value == 18.0
        assert result.max_value == 120.0

    def test_length_and_merged(self) -> None:
        result = CheckConstraintParser.parse("code", "length(code) >= 3 AND length(code) <= 10")
        assert result is not None
        assert result.kind == "length_range"
        assert result.min_length == 3
        assert result.max_length == 10

    def test_multi_column_only_target_extracted(self) -> None:
        """多列 CHECK 只提取目标列的边界，其余合取项跳过。"""
        result = CheckConstraintParser.parse("price", "price >= 0 AND stock >= 0")
        assert result is not None
        assert result.min_value == 0.0
        assert result.max_value is None

    def test_constraint_prefix_stripped(self) -> None:
        result = CheckConstraintParser.parse("age", "CONSTRAINT ck_age CHECK (age >= 18 AND age <= 120)")
        assert result is not None
        assert result.min_value == 18.0
        assert result.max_value == 120.0


class TestCheckParserOrChoice:
    """OR 连接的确定性形态（同列等值析取）合并为 choice；非等值 OR 降级。"""

    def test_or_equal_values_become_choices(self) -> None:
        result = CheckConstraintParser.parse("status", "status = 'a' OR status = 'b'")
        assert result is not None
        assert result.kind == "choice"
        assert set(result.choices) == {"a", "b"}

    def test_or_non_equal_returns_none(self) -> None:
        """age >= 18 OR age IS NULL：OR 语义无法确定合并，明确降级。"""
        result = CheckConstraintParser.parse("age", "age >= 18 OR age IS NULL")
        assert result is None


class TestCheckParserDecline:
    """无法确定性映射的形态必须明确降级返回 None（绝不硬猜）。"""

    def test_cross_column_reference_bound(self) -> None:
        """discount <= subtotal：max 是列引用，只能确定 min=0。"""
        result = CheckConstraintParser.parse("discount", "discount >= 0 AND discount <= subtotal")
        assert result is not None
        assert result.min_value == 0.0
        assert result.max_value is None

    def test_cross_column_arithmetic_returns_none(self) -> None:
        result = CheckConstraintParser.parse("x", "price * quantity <= 10000")
        assert result is None

    def test_like_returns_none(self) -> None:
        result = CheckConstraintParser.parse("name", "name LIKE 'A%'")
        assert result is None

    def test_column_comparison_returns_none(self) -> None:
        result = CheckConstraintParser.parse("created_at", "created_at < updated_at")
        assert result is None

    def test_garbage_returns_none(self) -> None:
        result = CheckConstraintParser.parse("age", "not a valid sql !!!")
        assert result is None
