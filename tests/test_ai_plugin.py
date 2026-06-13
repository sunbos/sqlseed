from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from sqlseed.core.orchestrator import DataOrchestrator
from tests.conftest import make_col

try:
    from openai import APITimeoutError
    from sqlseed_ai.analyzer import SchemaAnalyzer
    from sqlseed_ai.config import AIConfig

    HAS_SQLSEED_AI = True
except ImportError:
    HAS_SQLSEED_AI = False
    SchemaAnalyzer = None  # type: ignore
    AIConfig = None  # type: ignore
    APITimeoutError = None  # type: ignore

if not HAS_SQLSEED_AI:
    pytest.skip("sqlseed-ai plugin not installed", allow_module_level=True)


class TestAIConfig:
    def test_default_values(self) -> None:
        config = AIConfig()
        assert config.api_key is None
        assert config.model is None
        assert config.base_url is None
        assert config.temperature == pytest.approx(0.3)
        assert config.max_tokens == 0  # 0 means auto-resolve
        assert config.timeout == pytest.approx(0.0)  # 0 means auto-resolve

    def test_from_env_missing(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("SQLSEED_AI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("SQLSEED_AI_BASE_URL", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("SQLSEED_AI_MODEL", raising=False)
        monkeypatch.delenv("SQLSEED_AI_BACKEND", raising=False)
        monkeypatch.delenv("SQLSEED_AI_TIMEOUT", raising=False)
        config = AIConfig.from_env()
        assert config.api_key is None
        assert config.base_url is None
        assert config.model is None
        assert config.timeout == pytest.approx(0.0)  # 0 means auto-resolve

    def test_from_env_set(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("SQLSEED_AI_API_KEY", "sk-test123")
        monkeypatch.setenv("SQLSEED_AI_BASE_URL", "https://api.test.com/v1")
        monkeypatch.setenv("SQLSEED_AI_MODEL", "gpt-4o")
        monkeypatch.setenv("SQLSEED_AI_TIMEOUT", "120")
        config = AIConfig.from_env()
        assert config.api_key == "sk-test123"
        assert config.base_url == "https://api.test.com/v1"
        assert config.model == "gpt-4o"
        assert config.timeout == pytest.approx(120.0)

    def test_from_env_fallback_openai(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("SQLSEED_AI_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-key")
        monkeypatch.delenv("SQLSEED_AI_BASE_URL", raising=False)
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        config = AIConfig.from_env()
        assert config.api_key == "sk-openai-key"
        assert config.base_url == "https://api.openai.com/v1"

    def test_resolve_model_user_override(self) -> None:
        config = AIConfig(model="gpt-4o")
        result = config.resolve_model()
        assert result == "gpt-4o"
        assert config.model == "gpt-4o"

    def test_resolve_model_auto_detect_local(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("SQLSEED_AI_BACKEND", "lm_studio")
        config = AIConfig.from_env()
        # Mock _detect_local_model to return None (no local server running)
        monkeypatch.setattr(config, "_detect_local_model", lambda: None)
        result = config.resolve_model()
        # LM Studio uses "google/gemma-4-e4b" format (not "gemma-4-e4b-it")
        assert result == "google/gemma-4-e4b"

    def test_resolve_max_tokens_auto(self) -> None:
        config = AIConfig(backend="lm_studio", model="google/gemma-4-e4b")
        config.resolve_model()
        # E4B with reasoning_effort=none: 768 covers up to ~30-column tables
        assert config.resolve_max_tokens() == 768

    def test_resolve_max_tokens_explicit(self) -> None:
        config = AIConfig(max_tokens=2048)
        assert config.resolve_max_tokens() == 2048


class TestCallLLMFallback:
    def test_call_llm_fallback_on_timeout(self) -> None:
        config = AIConfig(api_key="test-key", model="model_a")
        analyzer = SchemaAnalyzer(config=config)

        call_count = 0

        def mock_call_llm_once(_self, _messages, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise APITimeoutError(request=type("Request", (), {"body": None})())
            return {"name": "test", "count": 100, "columns": []}

        with (
            patch.object(SchemaAnalyzer, "_call_llm_once", mock_call_llm_once),
            patch("sqlseed_ai.analyzer.select_next_gemma_model", return_value="gemma-4-e4b-it"),
        ):
            result = analyzer.call_llm([{"role": "user", "content": "test"}])

        assert result == {"name": "test", "count": 100, "columns": []}
        assert analyzer._config is not None
        # Model fallback uses local variable, does NOT modify config.model
        assert analyzer._config.model == "model_a"

    def test_call_llm_no_more_fallback(self) -> None:
        config = AIConfig(api_key="test-key", model="model_c")
        analyzer = SchemaAnalyzer(config=config)

        def mock_call_llm_once(_self, _messages, **_kwargs):
            raise APITimeoutError(request=type("Request", (), {"body": None})())

        with (
            patch.object(SchemaAnalyzer, "_call_llm_once", mock_call_llm_once),
            patch("sqlseed_ai.analyzer.select_next_gemma_model", return_value=None),
            pytest.raises(RuntimeError, match="LLM API call failed"),
        ):
            analyzer.call_llm([{"role": "user", "content": "test"}])

    def test_call_llm_non_timeout_error_no_fallback(self) -> None:
        config = AIConfig(api_key="test-key", model="test-model")
        analyzer = SchemaAnalyzer(config=config)

        def mock_call_llm_once(_self, _messages, **_kwargs):
            raise RuntimeError("Some other error")

        with (
            patch.object(SchemaAnalyzer, "_call_llm_once", mock_call_llm_once),
            pytest.raises(RuntimeError, match="Some other error"),
        ):
            analyzer.call_llm([{"role": "user", "content": "test"}])


class TestSchemaAnalyzer:
    def test_build_context_basic(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        columns = [
            make_col("project_no", "VARCHAR(20)"),
            make_col("member_no", "VARCHAR(32)"),
            make_col("projectId", "INTEGER", is_pk=True, is_auto=True),
        ]
        context = analyzer._build_context(
            {
                "table_name": "projects",
                "columns": columns,
                "indexes": [],
                "sample_data": [],
                "foreign_keys": [],
                "all_table_names": ["projects", "user_info"],
            }
        )
        assert "projects" in context
        assert "project_no" in context
        assert "member_no" in context
        assert "PRIMARY KEY" in context
        assert "AUTOINCREMENT" in context

    def test_build_context_with_indexes(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        columns = [make_col("project_no", "VARCHAR(20)")]
        indexes = [{"name": "idx_project", "columns": ["project_no"], "unique": True}]
        context = analyzer._build_context(
            {
                "table_name": "projects",
                "columns": columns,
                "indexes": indexes,
                "sample_data": [],
                "foreign_keys": [],
                "all_table_names": ["projects"],
            }
        )
        assert "UNIQUE" in context
        assert "INDEX" in context

    def test_build_context_with_foreign_keys(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        columns = [make_col("user_id", "INTEGER")]
        fks = [type("FK", (), {"column": "user_id", "ref_table": "users", "ref_column": "id"})()]
        context = analyzer._build_context(
            {
                "table_name": "orders",
                "columns": columns,
                "indexes": [],
                "sample_data": [],
                "foreign_keys": fks,
                "all_table_names": ["users", "orders"],
            }
        )
        assert "Foreign Keys" in context
        assert "user_id" in context

    def test_build_context_with_sample_data(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        columns = [make_col("name", "TEXT")]
        sample_data = [{"name": "Alice"}, {"name": "Bob"}]
        context = analyzer._build_context(
            {
                "table_name": "users",
                "columns": columns,
                "indexes": [],
                "sample_data": sample_data,
                "foreign_keys": [],
                "all_table_names": ["users"],
            }
        )
        assert "Sample Data" in context
        assert "Alice" in context

    def test_analyze_table_returns_none_without_api_key(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(api_key=None, model="test-model"))
        result = analyzer.analyze_table_from_ctx(
            table_name="test",
            columns=[],
            indexes=[],
            sample_data=[],
            foreign_keys=[],
            all_table_names=[],
        )
        assert result is None

    def test_parse_json_response_plain(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        json_str = '{"name": "test", "count": 100, "columns": [{"name": "id", "generator": "integer"}]}'
        result = analyzer._parse_json_response(json_str)
        assert result["name"] == "test"
        assert result["count"] == 100

    def test_parse_json_response_with_fences(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        json_str = '```json\n{"name": "test", "count": 100}\n```'
        result = analyzer._parse_json_response(json_str)
        assert result["name"] == "test"

    def test_parse_json_response_with_plain_fences(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        json_str = '```\n{"name": "test", "count": 100}\n```'
        result = analyzer._parse_json_response(json_str)
        assert result["name"] == "test"

    def test_parse_json_response_invalid(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        result = analyzer._parse_json_response("not valid json [[[")
        assert result == {}

    def test_parse_json_response_non_dict(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        result = analyzer._parse_json_response("[1, 2, 3]")
        assert result == {}

    def test_build_initial_messages(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        columns = [make_col("name", "TEXT")]
        messages = analyzer.build_initial_messages(
            {
                "table_name": "users",
                "columns": columns,
                "indexes": [],
                "sample_data": [],
                "foreign_keys": [],
                "all_table_names": ["users"],
            }
        )
        assert len(messages) == 10
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[2]["role"] == "assistant"
        assert messages[-1]["role"] == "user"
        assert "users" in messages[-1]["content"]

    def test_build_context_with_distribution(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        columns = [make_col("name", "TEXT")]
        distribution = [
            {
                "column": "name",
                "distinct_count": 50,
                "null_ratio": 0.1,
                "top_values": [{"value": "Alice", "frequency": 0.3}],
                "value_range": None,
            }
        ]
        context = analyzer._build_context(
            {
                "table_name": "users",
                "columns": columns,
                "indexes": [],
                "sample_data": [],
                "foreign_keys": [],
                "all_table_names": ["users"],
                "distribution": distribution,
            }
        )
        assert "Column Distribution" in context
        assert "50 distinct values" in context
        assert "10.0% null" in context
        assert "Alice" in context

    def test_generate_template_values(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(api_key="test-key", model="test-model"))
        with patch.object(analyzer, "call_llm", return_value={"values": ["v1", "v2", "v3"]}):
            result = analyzer.generate_template_values("project_no", "VARCHAR(20)", 3, [])
            assert result == ["v1", "v2", "v3"]

    def test_generate_template_values_empty(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(api_key="test-key", model="test-model"))
        with patch.object(analyzer, "call_llm", return_value={}):
            result = analyzer.generate_template_values("project_no", "VARCHAR(20)", 3, [])
            assert result == []


class TestProjectInfoIntegration:
    def test_full_context_sniffer_flow(self, unique_test_db) -> None:
        with DataOrchestrator(unique_test_db) as orch:
            columns = orch._schema.get_column_info("projects")
            assert len(columns) == 7

            col_names = [c.name for c in columns]
            assert "project_no" in col_names
            assert "member_no" in col_names
            assert "short_code" in col_names
            assert "region_code" in col_names

            indexes = orch._schema.get_index_info("projects")
            assert len(indexes) == 2
            idx_map = {i.name: i for i in indexes}
            assert idx_map["idx_projectno"].unique is True
            assert idx_map["idx_memberno"].unique is True

            sample_data = orch._schema.get_sample_data("projects", limit=5)
            assert isinstance(sample_data, list)

            analyzer = SchemaAnalyzer(config=AIConfig(api_key=None, model="test-model"))
            fks = orch._db.get_foreign_keys("projects")
            all_tables = orch._db.get_table_names()

            context = analyzer._build_context(
                {
                    "table_name": "projects",
                    "columns": columns,
                    "indexes": [{"name": i.name, "columns": i.columns, "unique": i.unique} for i in indexes],
                    "sample_data": sample_data,
                    "foreign_keys": fks,
                    "all_table_names": all_tables,
                }
            )

            assert "projects" in context
            assert "project_no" in context
            assert "UNIQUE" in context
            assert "short_code" in context
            assert "NOT NULL" in context
