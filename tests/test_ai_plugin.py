from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest

from sqlseed.core.orchestrator import DataOrchestrator
from tests.conftest import make_col

try:
    from openai import APITimeoutError
    from sqlseed_ai._model_selector import (
        _CACHE,
        PREFERRED_FREE_MODELS,
        clear_cache,
        select_best_free_model,
        select_next_free_model,
    )
    from sqlseed_ai.analyzer import SchemaAnalyzer
    from sqlseed_ai.config import AIConfig

    HAS_SQLSEED_AI = True
except ImportError:
    HAS_SQLSEED_AI = False
    SchemaAnalyzer = None  # type: ignore
    AIConfig = None  # type: ignore
    select_best_free_model = None  # type: ignore
    select_next_free_model = None  # type: ignore
    clear_cache = None  # type: ignore
    PREFERRED_FREE_MODELS = []  # type: ignore
    _CACHE = {}  # type: ignore
    APITimeoutError = None  # type: ignore

if not HAS_SQLSEED_AI:
    pytest.skip("sqlseed-ai plugin not installed", allow_module_level=True)


def _make_mock_response(
    model_id: str,
    prompt_price: str = "0",
    completion_price: str = "0",
    input_mod: list[str] | None = None,
    output_mod: list[str] | None = None,
    supported_params: list[str] | None = None,
) -> type:
    if input_mod is None:
        input_mod = ["text"]
    if output_mod is None:
        output_mod = ["text"]
    if supported_params is None:
        supported_params = ["response_format"]

    body = json.dumps(
        {
            "data": [
                {
                    "id": model_id,
                    "pricing": {"prompt": prompt_price, "completion": completion_price},
                    "architecture": {"input_modalities": input_mod, "output_modalities": output_mod},
                    "supported_parameters": supported_params,
                }
            ]
        }
    ).encode()

    return type(
        "Response",
        (),
        {
            "read": lambda self: body,
            "__enter__": lambda self: self,
            "__exit__": lambda self, *args: None,
        },
    )


class TestAIConfig:
    def test_default_values(self):
        config = AIConfig()
        assert config.api_key is None
        assert config.model is None
        assert config.base_url == "https://openrouter.ai/api/v1"
        assert config.temperature == pytest.approx(0.3)
        assert config.max_tokens == 4096
        assert config.timeout == pytest.approx(60.0)

    def test_from_env_missing(self, monkeypatch):
        monkeypatch.delenv("SQLSEED_AI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("SQLSEED_AI_BASE_URL", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("SQLSEED_AI_MODEL", raising=False)
        monkeypatch.delenv("SQLSEED_AI_TIMEOUT", raising=False)
        config = AIConfig.from_env()
        assert config.api_key is None
        assert config.base_url == "https://openrouter.ai/api/v1"
        assert config.model is None
        assert config.timeout == pytest.approx(60.0)

    def test_from_env_set(self, monkeypatch):
        monkeypatch.setenv("SQLSEED_AI_API_KEY", "sk-test123")
        monkeypatch.setenv("SQLSEED_AI_BASE_URL", "https://api.test.com/v1")
        monkeypatch.setenv("SQLSEED_AI_MODEL", "gpt-4o")
        monkeypatch.setenv("SQLSEED_AI_TIMEOUT", "120")
        config = AIConfig.from_env()
        assert config.api_key == "sk-test123"
        assert config.base_url == "https://api.test.com/v1"
        assert config.model == "gpt-4o"
        assert config.timeout == pytest.approx(120.0)

    def test_from_env_fallback_openai(self, monkeypatch):
        monkeypatch.delenv("SQLSEED_AI_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-key")
        monkeypatch.delenv("SQLSEED_AI_BASE_URL", raising=False)
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        config = AIConfig.from_env()
        assert config.api_key == "sk-openai-key"
        assert config.base_url == "https://api.openai.com/v1"

    def test_resolve_model_auto_select(self):
        clear_cache()
        config = AIConfig()
        assert config.model is None
        with patch("sqlseed_ai.config.select_best_free_model", return_value="test/model:free"):
            result = config.resolve_model()
        assert result == "test/model:free"
        assert config.model == "test/model:free"
        clear_cache()

    def test_resolve_model_user_override(self):
        config = AIConfig(model="gpt-4o")
        with patch("sqlseed_ai.config.select_best_free_model") as mock_select:
            result = config.resolve_model()
        mock_select.assert_not_called()
        assert result == "gpt-4o"
        assert config.model == "gpt-4o"


class TestModelSelector:
    def test_select_best_free_model_with_mock_api(self):
        clear_cache()
        mock_response = _make_mock_response("nvidia/nemotron-3-super-120b-a12b:free")

        with patch("sqlseed_ai._model_selector.urllib.request.urlopen", return_value=mock_response()):
            result = select_best_free_model()

        assert result == "nvidia/nemotron-3-super-120b-a12b:free"
        clear_cache()

    def test_select_best_free_model_api_failure(self):
        clear_cache()
        with patch("sqlseed_ai._model_selector.urllib.request.urlopen", side_effect=OSError("Network error")):
            result = select_best_free_model()

        assert result == PREFERRED_FREE_MODELS[0]
        clear_cache()

    def test_select_best_free_model_no_match(self):
        clear_cache()
        mock_response = _make_mock_response("other/free-model:free")

        with patch("sqlseed_ai._model_selector.urllib.request.urlopen", return_value=mock_response()):
            result = select_best_free_model()

        assert result == PREFERRED_FREE_MODELS[0]
        clear_cache()

    def test_select_best_free_model_caching(self):
        clear_cache()
        _CACHE["model"] = "cached/model:free"
        _CACHE["expires_at"] = time.time() + 3600

        result = select_best_free_model()
        assert result == "cached/model:free"
        clear_cache()

    def test_select_best_free_model_cache_expired(self):
        clear_cache()
        _CACHE["model"] = "expired/model:free"
        _CACHE["expires_at"] = time.time() - 1

        mock_response = _make_mock_response("tencent/hy3-preview:free")

        with patch("sqlseed_ai._model_selector.urllib.request.urlopen", return_value=mock_response()):
            result = select_best_free_model()

        assert result == "tencent/hy3-preview:free"
        clear_cache()

    def test_filter_non_text_model(self):
        clear_cache()
        mock_response = _make_mock_response(
            "nvidia/nemotron-3-super-120b-a12b:free",
            input_mod=["image", "text"],
            output_mod=["image"],
        )

        with patch("sqlseed_ai._model_selector.urllib.request.urlopen", return_value=mock_response()):
            result = select_best_free_model()

        assert result == PREFERRED_FREE_MODELS[0]
        clear_cache()

    def test_filter_no_response_format(self):
        clear_cache()
        mock_response = _make_mock_response(
            "nvidia/nemotron-3-super-120b-a12b:free",
            supported_params=["temperature"],
        )

        with patch("sqlseed_ai._model_selector.urllib.request.urlopen", return_value=mock_response()):
            result = select_best_free_model()

        assert result == PREFERRED_FREE_MODELS[0]
        clear_cache()

    def test_filter_paid_model(self):
        clear_cache()
        mock_response = _make_mock_response(
            "some/paid-model",
            prompt_price="0.001",
            completion_price="0.002",
        )

        with patch("sqlseed_ai._model_selector.urllib.request.urlopen", return_value=mock_response()):
            result = select_best_free_model()

        assert result == PREFERRED_FREE_MODELS[0]
        clear_cache()

    def test_select_next_free_model(self):
        clear_cache()
        result = select_next_free_model(PREFERRED_FREE_MODELS[0])
        assert result == PREFERRED_FREE_MODELS[1]
        clear_cache()

    def test_select_next_free_model_last(self):
        clear_cache()
        result = select_next_free_model(PREFERRED_FREE_MODELS[-1])
        assert result is None
        clear_cache()

    def test_select_next_free_model_unknown(self):
        clear_cache()
        result = select_next_free_model("unknown/model:free")
        assert result is None
        clear_cache()


class TestCallLLMFallback:
    def test_call_llm_fallback_on_timeout(self):
        config = AIConfig(api_key="test-key", model=PREFERRED_FREE_MODELS[0])
        analyzer = SchemaAnalyzer(config=config)

        call_count = 0

        def mock_call_llm_once(_self, _messages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise APITimeoutError(request=type("Request", (), {"body": None})())
            return {"name": "test", "count": 100, "columns": []}

        with (
            patch.object(SchemaAnalyzer, "_call_llm_once", mock_call_llm_once),
            patch("sqlseed_ai.analyzer.select_next_free_model", return_value=PREFERRED_FREE_MODELS[1]),
        ):
            result = analyzer.call_llm([{"role": "user", "content": "test"}])

        assert result == {"name": "test", "count": 100, "columns": []}
        assert analyzer._config.model == PREFERRED_FREE_MODELS[1]

    def test_call_llm_no_more_fallback(self):
        config = AIConfig(api_key="test-key", model=PREFERRED_FREE_MODELS[-1])
        analyzer = SchemaAnalyzer(config=config)

        def mock_call_llm_once(self, messages):
            raise APITimeoutError(request=type("Request", (), {"body": None})())

        with (
            patch.object(SchemaAnalyzer, "_call_llm_once", mock_call_llm_once),
            patch("sqlseed_ai.analyzer.select_next_free_model", return_value=None),
            pytest.raises(RuntimeError, match="LLM API call failed"),
        ):
            analyzer.call_llm([{"role": "user", "content": "test"}])

    def test_call_llm_non_timeout_error_no_fallback(self):
        config = AIConfig(api_key="test-key", model="test-model")
        analyzer = SchemaAnalyzer(config=config)

        def mock_call_llm_once(self, messages):
            raise RuntimeError("Some other error")

        with (
            patch.object(SchemaAnalyzer, "_call_llm_once", mock_call_llm_once),
            pytest.raises(RuntimeError, match="Some other error"),
        ):
            analyzer.call_llm([{"role": "user", "content": "test"}])


class TestSchemaAnalyzer:
    def test_build_context_basic(self):
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        columns = [
            make_col("card_number", "VARCHAR(20)"),
            make_col("account_id", "VARCHAR(32)"),
            make_col("cardId", "INTEGER", is_pk=True, is_auto=True),
        ]
        context = analyzer._build_context(
            {
                "table_name": "bank_cards",
                "columns": columns,
                "indexes": [],
                "sample_data": [],
                "foreign_keys": [],
                "all_table_names": ["bank_cards", "user_info"],
            }
        )
        assert "bank_cards" in context
        assert "card_number" in context
        assert "account_id" in context
        assert "PRIMARY KEY" in context
        assert "AUTOINCREMENT" in context

    def test_build_context_with_indexes(self):
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        columns = [make_col("card_number", "VARCHAR(20)")]
        indexes = [{"name": "idx_card", "columns": ["card_number"], "unique": True}]
        context = analyzer._build_context(
            {
                "table_name": "bank_cards",
                "columns": columns,
                "indexes": indexes,
                "sample_data": [],
                "foreign_keys": [],
                "all_table_names": ["bank_cards"],
            }
        )
        assert "UNIQUE" in context
        assert "INDEX" in context

    def test_build_context_with_foreign_keys(self):
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

    def test_build_context_with_sample_data(self):
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

    def test_analyze_table_returns_none_without_api_key(self):
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

    def test_parse_json_response_plain(self):
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        json_str = '{"name": "test", "count": 100, "columns": [{"name": "id", "generator": "integer"}]}'
        result = analyzer._parse_json_response(json_str)
        assert result["name"] == "test"
        assert result["count"] == 100

    def test_parse_json_response_with_fences(self):
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        json_str = '```json\n{"name": "test", "count": 100}\n```'
        result = analyzer._parse_json_response(json_str)
        assert result["name"] == "test"

    def test_parse_json_response_with_plain_fences(self):
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        json_str = '```\n{"name": "test", "count": 100}\n```'
        result = analyzer._parse_json_response(json_str)
        assert result["name"] == "test"

    def test_parse_json_response_invalid(self):
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        result = analyzer._parse_json_response("not valid json [[[")
        assert result == {}

    def test_parse_json_response_non_dict(self):
        analyzer = SchemaAnalyzer(config=AIConfig(model="test-model"))
        result = analyzer._parse_json_response("[1, 2, 3]")
        assert result == {}

    def test_build_initial_messages(self):
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

    def test_build_context_with_distribution(self):
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

    def test_generate_template_values(self):
        analyzer = SchemaAnalyzer(config=AIConfig(api_key="test-key", model="test-model"))
        with patch.object(analyzer, "call_llm", return_value={"values": ["v1", "v2", "v3"]}):
            result = analyzer.generate_template_values("card_number", "VARCHAR(20)", 3, [])
            assert result == ["v1", "v2", "v3"]

    def test_generate_template_values_empty(self):
        analyzer = SchemaAnalyzer(config=AIConfig(api_key="test-key", model="test-model"))
        with patch.object(analyzer, "call_llm", return_value={}):
            result = analyzer.generate_template_values("card_number", "VARCHAR(20)", 3, [])
            assert result == []


class TestCardInfoIntegration:
    def test_full_context_sniffer_flow(self, bank_cards_db):
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

            analyzer = SchemaAnalyzer(config=AIConfig(api_key=None, model="test-model"))
            fks = orch._db.get_foreign_keys("bank_cards")
            all_tables = orch._db.get_table_names()

            context = analyzer._build_context(
                {
                    "table_name": "bank_cards",
                    "columns": columns,
                    "indexes": [{"name": i.name, "columns": i.columns, "unique": i.unique} for i in indexes],
                    "sample_data": sample_data,
                    "foreign_keys": fks,
                    "all_table_names": all_tables,
                }
            )

            assert "bank_cards" in context
            assert "card_number" in context
            assert "UNIQUE" in context
            assert "last_eight" in context
            assert "NOT NULL" in context
