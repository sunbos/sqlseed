"""Tests for SchemaSemanticAnalyzer."""
from __future__ import annotations

from unittest.mock import MagicMock

from sqlseed_ai.schema_analyzer import AnalysisRequest, SchemaSemanticAnalyzer


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


class TestSchemaSemanticAnalyzerPrompt:
    """Test LLM prompt construction with target/context separation."""

    def test_prompt_includes_target_tables(self) -> None:
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        req = AnalysisRequest(
            target_tables=["orders"],
            context_tables=["users"],
            all_tables_schema={
                "orders": {"columns": [{"name": "id", "type": "INTEGER"}], "foreign_keys": [], "check_constraints": []},
                "users": {"columns": [{"name": "id", "type": "INTEGER"}], "foreign_keys": [], "check_constraints": []},
            },
        )
        messages = analyzer._build_llm_messages(req)
        assert len(messages) >= 1
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "orders" in user_msg["content"]
        assert "GENERATE YAML" in user_msg["content"] or "generate" in user_msg["content"].lower()

    def test_prompt_marks_context_tables_as_do_not_generate(self) -> None:
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        req = AnalysisRequest(
            target_tables=["orders"],
            context_tables=["users", "merchants"],
            all_tables_schema={},
        )
        messages = analyzer._build_llm_messages(req)
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "DO NOT generate" in user_msg["content"] or "do not generate" in user_msg["content"].lower()
        assert "users" in user_msg["content"]
        assert "merchants" in user_msg["content"]

    def test_prompt_includes_check_constraints(self) -> None:
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        req = AnalysisRequest(
            target_tables=["products"],
            context_tables=[],
            all_tables_schema={
                "products": {
                    "columns": [{"name": "price", "type": "REAL"}],
                    "foreign_keys": [],
                    "check_constraints": [
                        {"name": "chk_price", "columns": ["price"], "expression": "price >= 0"}
                    ],
                }
            },
        )
        messages = analyzer._build_llm_messages(req)
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "price >= 0" in user_msg["content"]
        assert "CHECK" in user_msg["content"] or "check" in user_msg["content"].lower()


class TestSchemaSemanticAnalyzerLLMCall:
    """Test LLM call delegation and output filtering."""

    def test_call_llm_delegates_to_analyzer(self) -> None:
        """_call_llm should delegate to SchemaAnalyzer._call_llm_once."""
        mock_config = MagicMock()
        analyzer = SchemaSemanticAnalyzer(config=mock_config)

        # Set the backing attribute directly because _analyzer is a property
        # without a setter (lazy-init). patch.object cannot override it.
        mock_sa = MagicMock()
        mock_sa._call_llm_once.return_value = {"tables": [{"name": "orders"}]}
        analyzer._sa = mock_sa

        messages = [{"role": "user", "content": "test"}]
        result = analyzer._call_llm(messages)

        assert result == {"tables": [{"name": "orders"}]}
        mock_sa._call_llm_once.assert_called_once_with(messages)

    def test_filter_to_targets_removes_context(self) -> None:
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config_dict = {
            "tables": [
                {"name": "orders", "columns": []},
                {"name": "users", "columns": []},
            ]
        }
        result = analyzer._filter_to_targets(config_dict, ["orders"])
        assert len(result["tables"]) == 1
        assert result["tables"][0]["name"] == "orders"

    def test_filter_to_targets_keeps_all_when_all_targets(self) -> None:
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config_dict = {
            "tables": [
                {"name": "orders", "columns": []},
                {"name": "items", "columns": []},
            ]
        }
        result = analyzer._filter_to_targets(config_dict, ["orders", "items"])
        assert len(result["tables"]) == 2
