"""Tests for CHECK constraint parser."""
from __future__ import annotations

from sqlseed.core.check_parser import CheckConstraintParser


class TestCheckParserInClause:
    """Test parsing of CHECK(x IN ('A', 'B', 'C'))."""

    def test_parse_string_in_clause(self) -> None:
        result = CheckConstraintParser.parse(
            "status", "status IN ('active', 'inactive', 'pending')"
        )
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
        assert CheckConstraintParser.is_cross_column(
            "sale_price >= cost_price", ["sale_price", "cost_price"]
        ) is True

    def test_is_cross_column_single_column(self) -> None:
        assert CheckConstraintParser.is_cross_column(
            "price >= 0", ["price", "cost"]
        ) is False

    def test_is_cross_column_no_substring_false_positive(self) -> None:
        """Word boundary: 'price' must NOT match inside 'unit_price'.

        Regression test for v3 correction #6: substring matching caused
        false positive cross-column detection.
        """
        # 'price' should NOT be detected in 'unit_price >= 100'
        assert CheckConstraintParser.is_cross_column(
            "unit_price >= 100", ["price", "unit_price"]
        ) is False

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
