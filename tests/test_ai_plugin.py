from __future__ import annotations

import sqlite3

import pytest

from sqlseed_ai.analyzer import SchemaAnalyzer
from sqlseed_ai.config import AIConfig


class TestAIConfig:
    def test_default_values(self):
        config = AIConfig()
        assert config.api_key is None
        assert config.model == "qwen3-coder-plus"
        assert config.base_url is None
        assert config.temperature == 0.3
        assert config.max_tokens == 4096

    def test_from_env_missing(self, monkeypatch):
        monkeypatch.delenv("SQLSEED_AI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("SQLSEED_AI_BASE_URL", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("SQLSEED_AI_MODEL", raising=False)
        config = AIConfig.from_env()
        assert config.api_key is None
        assert config.base_url is None
        assert config.model == "qwen3-coder-plus"

    def test_from_env_set(self, monkeypatch):
        monkeypatch.setenv("SQLSEED_AI_API_KEY", "sk-test123")
        monkeypatch.setenv("SQLSEED_AI_BASE_URL", "https://api.test.com/v1")
        monkeypatch.setenv("SQLSEED_AI_MODEL", "gpt-4o")
        config = AIConfig.from_env()
        assert config.api_key == "sk-test123"
        assert config.base_url == "https://api.test.com/v1"
        assert config.model == "gpt-4o"

    def test_from_env_fallback_openai(self, monkeypatch):
        monkeypatch.delenv("SQLSEED_AI_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-key")
        monkeypatch.delenv("SQLSEED_AI_BASE_URL", raising=False)
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        config = AIConfig.from_env()
        assert config.api_key == "sk-openai-key"
        assert config.base_url == "https://api.openai.com/v1"


class TestSchemaAnalyzer:
    def _make_col(self, name: str, col_type: str = "TEXT", nullable: bool = False,
                  default=None, is_pk: bool = False, is_auto: bool = False):
        return type("Col", (), {
            "name": name, "type": col_type, "nullable": nullable,
            "default": default, "is_primary_key": is_pk, "is_autoincrement": is_auto,
        })()

    def test_build_context_basic(self):
        analyzer = SchemaAnalyzer()
        columns = [
            self._make_col("card_number", "VARCHAR(20)"),
            self._make_col("account_id", "VARCHAR(32)"),
            self._make_col("cardId", "INTEGER", is_pk=True, is_auto=True),
        ]
        context = analyzer._build_context(
            table_name="bank_cards",
            columns=columns,
            indexes=[],
            sample_data=[],
            foreign_keys=[],
            all_table_names=["bank_cards", "user_info"],
        )
        assert "bank_cards" in context
        assert "card_number" in context
        assert "account_id" in context
        assert "PRIMARY KEY" in context
        assert "AUTOINCREMENT" in context

    def test_build_context_with_indexes(self):
        analyzer = SchemaAnalyzer()
        columns = [self._make_col("card_number", "VARCHAR(20)")]
        indexes = [{"name": "idx_card", "columns": ["card_number"], "unique": True}]
        context = analyzer._build_context(
            table_name="bank_cards",
            columns=columns,
            indexes=indexes,
            sample_data=[],
            foreign_keys=[],
            all_table_names=["bank_cards"],
        )
        assert "UNIQUE" in context
        assert "INDEX" in context

    def test_build_context_with_foreign_keys(self):
        analyzer = SchemaAnalyzer()
        columns = [self._make_col("user_id", "INTEGER")]
        fks = [type("FK", (), {"column": "user_id", "ref_table": "users", "ref_column": "id"})()]
        context = analyzer._build_context(
            table_name="orders",
            columns=columns,
            indexes=[],
            sample_data=[],
            foreign_keys=fks,
            all_table_names=["users", "orders"],
        )
        assert "Foreign Keys" in context
        assert "user_id" in context

    def test_build_context_with_sample_data(self):
        analyzer = SchemaAnalyzer()
        columns = [self._make_col("name", "TEXT")]
        sample_data = [{"name": "Alice"}, {"name": "Bob"}]
        context = analyzer._build_context(
            table_name="users",
            columns=columns,
            indexes=[],
            sample_data=sample_data,
            foreign_keys=[],
            all_table_names=["users"],
        )
        assert "Sample Data" in context
        assert "Alice" in context

    def test_analyze_table_returns_none_without_api_key(self):
        analyzer = SchemaAnalyzer(config=AIConfig(api_key=None))
        result = analyzer.analyze_table(
            table_name="test",
            columns=[],
            indexes=[],
            sample_data=[],
            foreign_keys=[],
            all_table_names=[],
        )
        assert result is None

    def test_parse_yaml_response_plain(self):
        analyzer = SchemaAnalyzer()
        yaml_str = "name: test\ncount: 100\ncolumns:\n  - name: id\n    generator: integer"
        result = analyzer._parse_yaml_response(yaml_str)
        assert result["name"] == "test"
        assert result["count"] == 100

    def test_parse_yaml_response_with_fences(self):
        analyzer = SchemaAnalyzer()
        yaml_str = "```yaml\nname: test\ncount: 100\n```"
        result = analyzer._parse_yaml_response(yaml_str)
        assert result["name"] == "test"

    def test_parse_yaml_response_invalid(self):
        analyzer = SchemaAnalyzer()
        result = analyzer._parse_yaml_response("not valid yaml [[[")
        assert result == {}


class TestCardInfoIntegration:
    def test_full_context_sniffer_flow(self, bank_cards_db):
        from sqlseed.core.orchestrator import DataOrchestrator

        with DataOrchestrator(bank_cards_db) as orch:
            columns = orch._schema.get_column_info("bank_cards")
            assert len(columns) == 7

            col_names = [c.name for c in columns]
            assert "card_number" in col_names
            assert "account_id" in col_names
            assert "last_eight" in col_names
            assert "last_six" in col_names

            indexes = orch._schema.get_index_info("bank_cards")
            assert len(indexes) == 2
            idx_map = {i.name: i for i in indexes}
            assert idx_map["idx_cardno"].unique is True
            assert idx_map["idx_userno"].unique is True

            sample_data = orch._schema.get_sample_data("bank_cards", limit=5)
            assert isinstance(sample_data, list)

            analyzer = SchemaAnalyzer(config=AIConfig(api_key=None))
            fks = orch._db.get_foreign_keys("bank_cards")
            all_tables = orch._db.get_table_names()

            context = analyzer._build_context(
                table_name="bank_cards",
                columns=columns,
                indexes=[{"name": i.name, "columns": i.columns, "unique": i.unique} for i in indexes],
                sample_data=sample_data,
                foreign_keys=fks,
                all_table_names=all_tables,
            )

            assert "bank_cards" in context
            assert "card_number" in context
            assert "UNIQUE" in context
            assert "last_eight" in context
            assert "NOT NULL" in context
