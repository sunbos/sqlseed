from __future__ import annotations

import json
import sqlite3
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import BaseModel, ValidationError

try:
    from sqlseed_ai.analyzer import SchemaAnalyzer
    from sqlseed_ai.config import AIConfig
    from sqlseed_ai.errors import ErrorSummary, summarize_error
    from sqlseed_ai.refiner import AiConfigRefiner, AISuggestionFailedError

    HAS_SQLSEED_AI = True
except ImportError:
    HAS_SQLSEED_AI = False
    SchemaAnalyzer = None  # type: ignore
    AIConfig = None  # type: ignore
    ErrorSummary = None  # type: ignore
    summarize_error = None  # type: ignore
    AiConfigRefiner = None  # type: ignore
    AISuggestionFailedError = Exception  # type: ignore

if not HAS_SQLSEED_AI:
    pytest.skip("sqlseed-ai plugin not installed", allow_module_level=True)


class TestErrorSummary:
    def test_to_prompt_str_with_column(self) -> None:
        err = ErrorSummary(
            error_type="pydantic_validation",
            message="Field 'columns[0]': invalid",
            column="columns[0]",
            retryable=True,
        )
        s = err.to_prompt_str()
        assert "pydantic_validation" in s
        assert "columns[0]" in s
        assert "Affected Column" in s

    def test_to_prompt_str_without_column(self) -> None:
        err = ErrorSummary(
            error_type="json_syntax",
            message="parse error",
            column=None,
            retryable=True,
        )
        s = err.to_prompt_str()
        assert "Affected Column" not in s


class TestSummarizeError:
    def test_json_decode_error(self) -> None:
        err = json.JSONDecodeError("msg", "", 0)
        summary = summarize_error(err)
        assert summary.error_type == "json_syntax"
        assert summary.retryable is True

    def test_attribute_error_with_generate(self) -> None:
        err = AttributeError("'Provider' object has no attribute 'generate_credit_card'")
        summary = summarize_error(err)
        assert summary.error_type == "unknown_generator"
        assert "credit_card" in summary.message
        assert summary.retryable is True

    def test_file_not_found_error(self) -> None:
        err = FileNotFoundError("db not found")
        summary = summarize_error(err)
        assert summary.error_type == "fatal"
        assert summary.retryable is False

    def test_generic_error(self) -> None:
        err = RuntimeError("something went wrong")
        summary = summarize_error(err)
        assert summary.error_type == "runtime_error"
        assert summary.retryable is True

    def test_pydantic_validation_error(self) -> None:

        class Inner(BaseModel):
            value: int

        class Outer(BaseModel):
            items: list[Inner]

        try:
            Outer(items=[{"value": "not_int"}])  # type: ignore
        except ValidationError as e:
            summary = summarize_error(e)
            assert summary.error_type == "pydantic_validation"
            assert summary.retryable is True


class TestAiConfigRefiner:
    def _make_refiner(self, tmp_path: Any, _llm_side_effect=None):
        analyzer = SchemaAnalyzer(config=AIConfig(api_key="test-key", model="test-model"))
        return AiConfigRefiner(
            analyzer,
            str(tmp_path / "test.db"),
            cache_dir=str(tmp_path / "cache"),
        )

    def test_cache_on_success(self, tmp_path: Any) -> None:
        refiner = self._make_refiner(tmp_path)
        config = {"name": "users", "count": 10, "columns": []}
        refiner._cache_successful_config("users", config, "abc123")

        cached = refiner.get_cached_config("users", "abc123")
        assert cached is not None
        assert cached["name"] == "users"

    def test_cache_schema_hash_mismatch(self, tmp_path: Any) -> None:
        refiner = self._make_refiner(tmp_path)
        config = {"name": "users", "count": 10, "columns": []}
        refiner._cache_successful_config("users", config, "abc123")

        cached = refiner.get_cached_config("users", "different_hash")
        assert cached is None

    def test_cache_miss(self, tmp_path: Any) -> None:
        refiner = self._make_refiner(tmp_path)
        assert refiner.get_cached_config("nonexistent") is None

    def test_refine_first_attempt_success(self, tmp_path: Any) -> None:

        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        conn.commit()
        conn.close()

        valid_config = {
            "name": "users",
            "count": 10,
            "columns": [{"name": "name", "generator": "string"}],
        }

        refiner = self._make_refiner(tmp_path)

        with patch.object(refiner._analyzer, "call_llm", return_value=valid_config):
            result = refiner.generate_and_refine("users", max_retries=3)

        assert result["name"] == "users"

    def test_refine_exhausts_retries(self, tmp_path: Any) -> None:
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        conn.commit()
        conn.close()

        invalid_config = {"invalid": True}

        refiner = self._make_refiner(tmp_path)

        with (
            patch.object(refiner._analyzer, "call_llm", return_value=invalid_config),
            pytest.raises(AISuggestionFailedError, match="Failed after"),
        ):
            refiner.generate_and_refine("users", max_retries=2)

    def test_refine_non_retryable_exits(self, tmp_path: Any) -> None:
        refiner = self._make_refiner(tmp_path)

        with (
            patch.object(refiner._analyzer, "call_llm", side_effect=FileNotFoundError("db missing")),
            pytest.raises(AISuggestionFailedError, match="Non-retryable"),
        ):
            refiner.generate_and_refine("users", max_retries=3)

    def test_messages_accumulate(self, tmp_path: Any) -> None:
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        conn.commit()
        conn.close()

        invalid_config = {"invalid": True}
        call_count = 0
        captured_messages: list[Any] = []

        def mock_call_llm(messages):
            nonlocal call_count, captured_messages
            call_count += 1
            captured_messages.clear()
            captured_messages.extend(messages)
            if call_count >= 2:
                return {"name": "users", "count": 10, "columns": [{"name": "name", "generator": "string"}]}
            return invalid_config

        refiner = self._make_refiner(tmp_path)

        with (
            patch.object(
                refiner._analyzer,
                "build_initial_messages",
                return_value=[
                    {"role": "system", "content": "system"},
                    {"role": "user", "content": "context"},
                ],
            ),
            patch.object(refiner._analyzer, "call_llm", side_effect=mock_call_llm),
        ):
            result = refiner.generate_and_refine("users", max_retries=3)

        assert result["name"] == "users"
        assert call_count == 2
        assert len(captured_messages) == 4

    def test_build_refinement_prompt_last_attempt(self, tmp_path: Any) -> None:
        refiner = self._make_refiner(tmp_path)
        error = ErrorSummary(
            error_type="runtime_error",
            message="test error",
            column=None,
            retryable=True,
        )
        prompt = refiner._build_refinement_prompt(error, attempt=2, max_retries=3)
        assert "LAST attempt" in prompt

    def test_build_refinement_prompt_not_last(self, tmp_path: Any) -> None:
        refiner = self._make_refiner(tmp_path)
        error = ErrorSummary(
            error_type="runtime_error",
            message="test error",
            column=None,
            retryable=True,
        )
        prompt = refiner._build_refinement_prompt(error, attempt=0, max_retries=3)
        assert "LAST attempt" not in prompt
