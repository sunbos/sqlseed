"""Tests for CHECK constraint parser."""
from __future__ import annotations

from sqlseed.core.check_parser import CheckConstraintParser, ParsedCheck


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
