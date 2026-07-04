"""Tests for the sqlseed-ai plugin integration."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from sqlseed.core.orchestrator import DataOrchestrator
from tests._helpers import (
    clear_llm_env,
    configure_llm_backend_env,
    ensure_pg_users_table,
)
from tests.conftest import make_column_info

try:
    from openai import APITimeoutError
    from sqlseed_ai.analyzer import SchemaAnalyzer
    from sqlseed_ai.config import AIConfig
except ImportError:
    # pytest.skip with allow_module_level=True raises NoReturn — mypy
    # understands the except branch does not fall through, so the names
    # imported in the try branch are definitely bound for the rest of
    # the module. No placeholder None assignments or type: ignore needed.
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

    def test_from_env_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clear_llm_env(monkeypatch)
        config = AIConfig.from_env()
        assert config.api_key is None
        assert config.base_url is None
        assert config.model is None
        assert config.timeout == pytest.approx(0.0)  # 0 means auto-resolve

    def test_from_env_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SQLSEED_AI_API_KEY", "sk-test123")
        monkeypatch.setenv("SQLSEED_AI_BASE_URL", "https://api.test.com/v1")
        monkeypatch.setenv("SQLSEED_AI_MODEL", "gpt-4o")
        monkeypatch.setenv("SQLSEED_AI_TIMEOUT", "120")
        config = AIConfig.from_env()
        assert config.api_key == "sk-test123"
        assert config.base_url == "https://api.test.com/v1"
        assert config.model == "gpt-4o"
        assert config.timeout == pytest.approx(120.0)

    def test_from_env_fallback_openai(self, monkeypatch: pytest.MonkeyPatch) -> None:
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

    def test_resolve_model_auto_detect_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SQLSEED_AI_BACKEND", "lm_studio")
        # Clear SQLSEED_AI_MODEL so config.model is None, forcing resolve_model()
        # to exercise the auto-detect path rather than short-circuiting on a
        # user-supplied model. Without this, a SQLSEED_AI_MODEL env var leaked
        # from a prior session (e.g., "google/gemma-4-e2b") would cause the
        # test to assert against the wrong fallback model.
        monkeypatch.delenv("SQLSEED_AI_MODEL", raising=False)
        config = AIConfig.from_env()
        # Mock _detect_local_model to return None (no local server running)
        monkeypatch.setattr(config, "_detect_local_model", lambda: None)
        result = config.resolve_model()
        # LM Studio uses "google/gemma-4-e4b" format (not "gemma-4-e4b-it")
        assert result == "google/gemma-4-e4b"

    def test_resolve_max_tokens_auto(self) -> None:
        config = AIConfig(backend="lm_studio", model="google/gemma-4-e4b")
        config.resolve_model()
        # E4B reasoning models need larger budget for complete JSON output
        assert config.resolve_max_tokens() == 4096

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
            patch("sqlseed_ai.analyzer._caller.select_next_gemma_model", return_value="gemma-4-e4b-it"),
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
            patch("sqlseed_ai.analyzer._caller.select_next_gemma_model", return_value=None),
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
            make_column_info("project_no", "VARCHAR(20)"),
            make_column_info("member_no", "VARCHAR(32)"),
            make_column_info("projectId", "INTEGER", is_primary_key=True, is_autoincrement=False),
            make_column_info("autoId", "INTEGER", is_primary_key=True, is_autoincrement=True),
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
        assert "autoId" not in context

    def test_build_context_with_indexes(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        columns = [make_column_info("project_no", "VARCHAR(20)")]
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
        columns = [make_column_info("user_id", "INTEGER")]
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
        columns = [make_column_info("name", "TEXT")]
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
        assert isinstance(result, dict)
        assert result["name"] == "test"
        assert result["count"] == 100

    def test_parse_json_response_with_fences(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        json_str = '```json\n{"name": "test", "count": 100}\n```'
        result = analyzer._parse_json_response(json_str)
        assert isinstance(result, dict)
        assert result["name"] == "test"

    def test_parse_json_response_with_plain_fences(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        json_str = '```\n{"name": "test", "count": 100}\n```'
        result = analyzer._parse_json_response(json_str)
        assert isinstance(result, dict)
        assert result["name"] == "test"

    def test_parse_json_response_invalid(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        result = analyzer._parse_json_response("not valid json [[[")
        assert not result

    def test_parse_json_response_non_dict(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        result = analyzer._parse_json_response("[1, 2, 3]")
        assert not result

    def test_build_initial_messages(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        columns = [make_column_info("name", "TEXT")]
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
        # Expected structure: 1 system + (N few-shot pairs = 2*N) + 1 actual query.
        # Computing from FEW_SHOT_EXAMPLES makes the test robust against
        # future few-shot additions (was hardcoded to 10, broke at 14 after
        # P0-P3 examples were added).
        from sqlseed_ai.examples import FEW_SHOT_EXAMPLES

        expected_count = 1 + len(FEW_SHOT_EXAMPLES) * 2 + 1
        assert len(messages) == expected_count, (
            f"expected {expected_count} messages (1 system + "
            f"{len(FEW_SHOT_EXAMPLES)}*2 few-shot pairs + 1 query), "
            f"got {len(messages)}"
        )
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[2]["role"] == "assistant"
        assert messages[-1]["role"] == "user"
        assert "users" in messages[-1]["content"]

    def test_build_context_with_distribution(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        columns = [make_column_info("name", "TEXT")]
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
            assert not result


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


class TestSchemaAnalyzerDialect:
    """Tests for SchemaAnalyzer dialect context propagation (includes real LLM calls)."""

    @pytest.mark.parametrize("dialect", ["sqlite", "postgresql"])
    def test_build_context_with_dialect(self, dialect: str) -> None:
        """dialect field produces output containing "Database dialect: <dialect>"."""
        analyzer = SchemaAnalyzer(AIConfig())
        schema_ctx = {
            "table_name": "users",
            "columns": [
                make_column_info("id", "INTEGER", is_primary_key=True, is_autoincrement=True),
                make_column_info("name", "TEXT"),
            ],
            "indexes": [],
            "foreign_keys": [],
            "all_table_names": ["users"],
            "sample_data": [],
            "dialect": dialect,
        }
        context = analyzer._build_context(schema_ctx)
        assert f"Database dialect: {dialect}" in context

    def test_build_context_default_dialect_is_sqlite(self) -> None:
        """When dialect is not provided, it defaults to "sqlite"."""
        analyzer = SchemaAnalyzer(AIConfig())
        schema_ctx = {
            "table_name": "users",
            "columns": [make_column_info("id", "INTEGER")],
            "indexes": [],
            "foreign_keys": [],
            "all_table_names": ["users"],
            "sample_data": [],
        }
        context = analyzer._build_context(schema_ctx)
        assert "Database dialect: sqlite" in context

    def _make_real_llm_analyzer(
        self, monkeypatch: pytest.MonkeyPatch, available_llm_backend: dict[str, str]
    ) -> SchemaAnalyzer:
        """Configure backend env vars from the session fixture and return a SchemaAnalyzer.

        Shared by the real-LLM integration tests to eliminate the repeated
        ``backend = ...; model = ...; configure_llm_backend_env(...); config = ...;
        analyzer = ...`` setup block.
        """
        backend = available_llm_backend["backend"]
        model = available_llm_backend["model"]
        configure_llm_backend_env(monkeypatch, backend, model)
        return SchemaAnalyzer(AIConfig.from_env())

    def test_analyze_schema_sqlite_real_llm(
        self, tmp_db: str, available_llm_backend: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Real SQLite schema analysis, verifying that the LLM returns a valid configuration."""
        analyzer = self._make_real_llm_analyzer(monkeypatch, available_llm_backend)

        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch._ensure_connected()
            schema_ctx = orch.get_schema_context("users")
            result = analyzer.analyze_table_from_ctx(**schema_ctx)

        # Verify that the LLM returns a valid structure
        assert result is not None, "LLM should return valid config, got None (API key missing or call failed)"
        assert isinstance(result, dict), f"LLM response should be a dict, got: {type(result)}"
        assert "tables" in result or "columns" in result, f"Unexpected LLM response structure: {result}"

    def test_analyze_schema_postgresql_real_llm(
        self, pg_url: str, available_llm_backend: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Real PG schema analysis, verifying that dialect propagates to the LLM prompt."""
        # First create the table on PG
        ensure_pg_users_table(pg_url)

        analyzer = self._make_real_llm_analyzer(monkeypatch, available_llm_backend)

        with DataOrchestrator(pg_url, provider_name="base") as orch:
            orch._ensure_connected()
            schema_ctx = orch.get_schema_context("users")
            # Verify that dialect propagates to the context
            assert schema_ctx.get("dialect") == "postgresql"
            # Verify that dialect propagates to the LLM prompt
            messages = analyzer.build_initial_messages(schema_ctx)
            result = analyzer.analyze_table_from_ctx(**schema_ctx)

        # Verify that the prompt contains PG dialect info (take the last user message, i.e. the context)
        user_messages = [m for m in messages if m["role"] == "user"]
        assert len(user_messages) > 0
        context_message = user_messages[-1]  # The last user message is the context
        assert "Database dialect: postgresql" in context_message["content"], (
            f"PG dialect was not propagated to the LLM prompt, prompt content: {context_message['content'][:200]}"
        )

        assert result is not None, "LLM should return a valid configuration"
        assert isinstance(result, dict), f"LLM response should be a dict, got: {type(result)}"

    def test_analyze_schema_dialect_in_prompt(
        self, pg_url: str, available_llm_backend: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Capture the actual prompt sent to the LLM and assert it contains "Database dialect: postgresql".

        Note: build_initial_messages() first adds the system message, then few-shot examples
        (user/assistant pairs), and finally adds the context as a user message. Therefore we
        must take the last user message (i.e. the context), not the first one.
        """
        # First create the table on PG
        ensure_pg_users_table(pg_url)

        analyzer = self._make_real_llm_analyzer(monkeypatch, available_llm_backend)

        with DataOrchestrator(pg_url, provider_name="base") as orch:
            orch._ensure_connected()
            schema_ctx = orch.get_schema_context("users")
            messages = analyzer.build_initial_messages(schema_ctx)

        # Take the last user message (i.e. the context, not a few-shot example)
        user_messages = [m for m in messages if m["role"] == "user"]
        assert len(user_messages) > 0
        context_message = user_messages[-1]
        assert "Database dialect: postgresql" in context_message["content"], (
            f"PG dialect was not propagated to the LLM prompt, prompt content: {context_message['content'][:200]}"
        )

    def test_analyze_schema_llm_response_structure(
        self, tmp_db: str, available_llm_backend: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify the LLM response structure (tables/columns/generators)."""
        analyzer = self._make_real_llm_analyzer(monkeypatch, available_llm_backend)

        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch._ensure_connected()
            schema_ctx = orch.get_schema_context("users")
            result = analyzer.analyze_table_from_ctx(**schema_ctx)

        assert result is not None, "LLM should return a valid configuration"
        # Verify that the response is a dict and contains a "tables" or "columns" key
        assert isinstance(result, dict), f"LLM response should be a dict, got: {type(result)}"
        has_key = "tables" in result or "columns" in result
        keys = list(result.keys()) if isinstance(result, dict) else "N/A"
        assert has_key, f"LLM response should contain a 'tables' or 'columns' key, actual keys: {keys}"

    def test_analyze_schema_llm_failure_clear_error(self, tmp_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """Simulate LLM timeout/error and verify that the error message is clear.

        Previously this test pointed at localhost:9999 to simulate a connection
        failure. However, when a real LLM backend (LM Studio/Ollama) is running
        locally, the analyzer may fall back to it and succeed, making the test
        environment-dependent. We now monkeypatch ``call_llm`` to deterministically
        raise a RuntimeError, verifying the error-handling path returns None.
        """
        config = AIConfig(model="test-model")
        analyzer = SchemaAnalyzer(config)

        # Force the LLM call to fail with a recoverable error.
        def _boom(messages: list[dict[str, str]]) -> dict[str, Any]:
            raise RuntimeError("simulated LLM failure")

        monkeypatch.setattr(analyzer, "call_llm", _boom)

        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch._ensure_connected()
            schema_ctx = orch.get_schema_context("users")
            # A failed call should return None (rather than raising an exception and crashing)
            result = analyzer.analyze_table_from_ctx(**schema_ctx)

        # On failure, returns None without crashing
        assert result is None
