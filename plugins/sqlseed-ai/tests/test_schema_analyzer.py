"""Tests for SchemaSemanticAnalyzer."""
from __future__ import annotations

from unittest.mock import MagicMock

from sqlseed_ai.schema_analyzer import SchemaSemanticAnalyzer


class TestSchemaSemanticAnalyzerStructure:
    """Test analyzer structure and request building."""

    def test_analyzer_creation(self) -> None:
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        assert analyzer is not None

    def test_build_request_full_database(self) -> None:
        """Full database analysis: tables=None means all tables."""
        db = MagicMock()
        db.get_table_names.return_value = ["users", "orders", "items"]
        db.get_column_info.return_value = []
        db.get_foreign_keys.return_value = []
        db.get_check_constraints.return_value = []
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        req = analyzer.build_request(db, tables=None)
        assert req.target_tables == ["users", "orders", "items"]
        assert req.context_tables == []

    def test_build_request_partial_with_deps(self) -> None:
        """Partial analysis with dependency resolution."""
        db = MagicMock()
        db.get_table_names.return_value = ["users", "orders", "items", "categories"]
        from sqlseed.database._protocol import ForeignKeyInfo
        db.get_foreign_keys.side_effect = lambda t: {
            "orders": [ForeignKeyInfo(column="user_id", ref_table="users", ref_column="id")],
            "users": [],
        }.get(t, [])
        db.get_column_info.return_value = []
        db.get_check_constraints.return_value = []
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        req = analyzer.build_request(db, tables=["orders"])
        assert req.target_tables == ["orders"]
        assert "users" in req.context_tables

    def test_build_request_partial_no_deps(self) -> None:
        """Partial analysis without dependencies."""
        db = MagicMock()
        db.get_table_names.return_value = ["users", "orders"]
        db.get_column_info.return_value = []
        db.get_foreign_keys.return_value = []
        db.get_check_constraints.return_value = []
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        req = analyzer.build_request(db, tables=["orders"], include_dependencies=False)
        assert req.target_tables == ["orders"]
        assert req.context_tables == []
