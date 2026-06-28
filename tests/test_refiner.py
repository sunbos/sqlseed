from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
from pydantic import BaseModel, ValidationError

from sqlseed.core.orchestrator import DataOrchestrator

try:
    from sqlseed_ai._prompts import _ULTRA_COMPACT_SYSTEM_PROMPT
    from sqlseed_ai.analyzer import SchemaAnalyzer
    from sqlseed_ai.config import AIBackend, AIConfig
    from sqlseed_ai.errors import ErrorSummary, summarize_error
    from sqlseed_ai.exceptions import ContextOverflowError
    from sqlseed_ai.refiner import AiConfigRefiner, AISuggestionFailedError, _RetryState
except ImportError:
    # pytest.skip with allow_module_level=True raises NoReturn — mypy
    # understands the except branch does not fall through, so the names
    # imported in the try branch are definitely bound for the rest of
    # the module. No placeholder None assignments or type: ignore needed.
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
        err = AttributeError("'Provider' object has no attribute 'generate_project_identifier'")
        summary = summarize_error(err)
        assert summary.error_type == "unknown_generator"
        assert "project_identifier" in summary.message
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
            # Intentionally pass wrong type (dict instead of Inner) to test
            # Pydantic validation. cast(Any, ...) tells mypy we know the
            # type is wrong — this is the error path we're verifying.
            Outer(items=cast("Any", [{"value": "not_int"}]))
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

    def _cache_config(self, tmp_path: Any, config: dict[str, Any], schema_hash: str = "abc123") -> AiConfigRefiner:
        refiner = self._make_refiner(tmp_path)
        refiner._cache_successful_config("users", config, schema_hash)
        return refiner

    def _create_users_db(self, tmp_path: Any) -> str:
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        conn.commit()
        conn.close()
        return db_path

    def _make_error_summary(self, error_type: str = "runtime_error", message: str = "test error") -> ErrorSummary:
        return ErrorSummary(error_type=error_type, message=message, column=None, retryable=True)

    def test_cache_on_success(self, tmp_path: Any) -> None:
        refiner = self._cache_config(tmp_path, {"name": "users", "count": 10, "columns": []})
        cached = refiner.get_cached_config("users", "abc123")
        assert cached is not None
        assert cached["name"] == "users"

    def test_cache_schema_hash_mismatch(self, tmp_path: Any) -> None:
        refiner = self._cache_config(tmp_path, {"name": "users", "count": 10, "columns": []})
        cached = refiner.get_cached_config("users", "different_hash")
        assert cached is None

    def test_cache_miss(self, tmp_path: Any) -> None:
        refiner = self._make_refiner(tmp_path)
        assert refiner.get_cached_config("nonexistent") is None

    def test_refine_first_attempt_success(self, tmp_path: Any) -> None:
        self._create_users_db(tmp_path)
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
        self._create_users_db(tmp_path)
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
        self._create_users_db(tmp_path)
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
        error = self._make_error_summary()
        prompt = refiner._build_refinement_prompt(error, attempt=2, max_retries=3)
        assert "LAST attempt" in prompt

    def test_build_refinement_prompt_not_last(self, tmp_path: Any) -> None:
        refiner = self._make_refiner(tmp_path)
        error = self._make_error_summary()
        prompt = refiner._build_refinement_prompt(error, attempt=0, max_retries=3)
        assert "LAST attempt" not in prompt


def _make_analyzer() -> SchemaAnalyzer:
    return SchemaAnalyzer(config=AIConfig(api_key="test-key", model="test-model"))


def _make_refiner(tmp_path: Any, db_path: str | None = None) -> AiConfigRefiner:
    return AiConfigRefiner(
        _make_analyzer(),
        db_path or str(tmp_path / "test.db"),
        cache_dir=str(tmp_path / "cache"),
    )


def _create_users_db(tmp_path: Any) -> str:
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
    conn.commit()
    conn.close()
    return db_path


def _valid_users_config() -> dict[str, Any]:
    return {"name": "users", "count": 10, "columns": [{"name": "name", "generator": "string"}]}


def _make_fail_then_succeed_streaming(
    valid_config: dict[str, Any], *, fail_until_call: int, error: Exception
) -> tuple[Any, list[int]]:
    """Build a mock ``call_llm_streaming`` that fails N times then succeeds.

    Extracted to avoid CodeDuplication between
    ``test_streaming_continues_after_generation_failure`` (RuntimeError on call 1)
    and ``test_streaming_implements_normal_to_ultra_compact_degradation``
    (ContextOverflowError on calls 1-2). Both tests previously inlined an
    identical ``mock_streaming`` closure that differed only in the failure
    condition and error type.

    Args:
        valid_config: config dict returned on the success call.
        fail_until_call: raise ``error`` for calls 1..fail_until_call (inclusive);
            succeed on call ``fail_until_call + 1``.
        error: exception instance to raise on failing calls.

    Returns:
        ``(mock_fn, call_log)`` where ``call_log`` is a list that records one
        entry per invocation; use ``len(call_log)`` to assert the call count.
    """
    call_log: list[int] = []

    def mock_streaming(_msgs: list[dict[str, str]], on_progress: Any = None) -> dict[str, Any]:
        del on_progress
        call_log.append(1)
        if len(call_log) <= fail_until_call:
            raise error
        return valid_config

    return mock_streaming, call_log


class TestRetryBudgetHandling:
    """Tests for _handle_generation_failure and _handle_validation_failure."""

    def _make_error(self, retryable: bool = True, error_type: str = "runtime_error") -> ErrorSummary:
        return ErrorSummary(error_type=error_type, message="test error", column=None, retryable=retryable)

    def test_handle_generation_failure_raises_when_max_retries_exhausted(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        error = self._make_error(retryable=True)
        with pytest.raises(AISuggestionFailedError, match="Failed after"):
            refiner._handle_generation_failure(error, attempt=2, max_retries=2)

    def test_handle_generation_failure_raises_on_non_retryable(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        error = self._make_error(retryable=False)
        with pytest.raises(AISuggestionFailedError, match="Non-retryable"):
            refiner._handle_generation_failure(error, attempt=0, max_retries=3)

    def test_handle_generation_failure_does_not_raise_when_retryable_and_below_max(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        error = self._make_error(retryable=True)
        # Should not raise
        refiner._handle_generation_failure(error, attempt=0, max_retries=3)

    def test_handle_validation_failure_raises_on_non_retryable(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        error = self._make_error(retryable=False)
        with pytest.raises(AISuggestionFailedError, match="Non-retryable"):
            refiner._handle_validation_failure(error, attempt=0, max_retries=3, table_name="users")

    def test_handle_validation_failure_raises_when_max_retries_exhausted(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        error = self._make_error(retryable=True)
        with pytest.raises(AISuggestionFailedError, match="Failed after"):
            refiner._handle_validation_failure(error, attempt=2, max_retries=2, table_name="users")


class TestRepeatedErrorDetection:
    """Tests for _check_repeated_error and _NON_RETRYABLE_ERRORS."""

    def _make_error(self, error_type: str = "json_syntax") -> ErrorSummary:
        return ErrorSummary(error_type=error_type, message="parse error", column=None, retryable=True)

    def test_same_non_retryable_error_twice_raises(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        error = self._make_error("json_syntax")
        # First occurrence: count becomes 1, no raise
        err_type, count = refiner._check_repeated_error(error, last_error_type=None, same_error_count=0)
        assert err_type == "json_syntax"
        assert count == 1
        # Second occurrence: count becomes 2, raises
        with pytest.raises(AISuggestionFailedError, match="Same error"):
            refiner._check_repeated_error(error, last_error_type="json_syntax", same_error_count=1)

    def test_error_type_change_resets_count_to_one(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        # Start tracking json_syntax
        error1 = self._make_error("json_syntax")
        _, count1 = refiner._check_repeated_error(error1, last_error_type=None, same_error_count=0)
        assert count1 == 1
        # Error type changes to empty_config: count resets to 1 (not 2)
        error2 = self._make_error("empty_config")
        err_type2, count2 = refiner._check_repeated_error(error2, last_error_type="json_syntax", same_error_count=1)
        assert err_type2 == "empty_config"
        assert count2 == 1

    def test_retryable_error_type_does_not_track_count(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        # runtime_error is not in _NON_RETRYABLE_ERRORS, count unchanged
        error = self._make_error("runtime_error")
        err_type, count = refiner._check_repeated_error(error, last_error_type="runtime_error", same_error_count=5)
        assert err_type == "runtime_error"
        assert count == 5

    def test_non_retryable_errors_includes_json_syntax(self) -> None:
        assert "json_syntax" in AiConfigRefiner._NON_RETRYABLE_ERRORS
        assert "invalid_json" not in AiConfigRefiner._NON_RETRYABLE_ERRORS

    def test_non_retryable_errors_includes_empty_config(self) -> None:
        assert "empty_config" in AiConfigRefiner._NON_RETRYABLE_ERRORS


class TestPromptLevels:
    """Tests for _get_prompt_levels and _resolve_use_compact."""

    def test_get_prompt_levels_compact_returns_single_ultra_level(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        levels = refiner._get_prompt_levels(use_compact=True)
        assert levels == [(True, True)]

    def test_get_prompt_levels_default_returns_three_levels(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        levels = refiner._get_prompt_levels(use_compact=False)
        assert levels == [(False, False), (True, False), (True, True)]

    def test_resolve_use_compact_returns_explicit_true(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        assert refiner._resolve_use_compact(True) is True

    def test_resolve_use_compact_returns_explicit_false(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        assert refiner._resolve_use_compact(False) is False

    def test_resolve_use_compact_auto_detect_false_when_no_config(self, tmp_path: Any) -> None:
        analyzer = SchemaAnalyzer(config=None)
        refiner = AiConfigRefiner(analyzer, str(tmp_path / "test.db"), cache_dir=str(tmp_path / "cache"))
        assert refiner._resolve_use_compact(None) is False

    def test_resolve_use_compact_auto_detect_true_for_small_local_model(self, tmp_path: Any) -> None:
        analyzer = SchemaAnalyzer(
            config=AIConfig(api_key="test-key", model="gemma-4-e4b-it", backend=AIBackend.OLLAMA),
        )
        refiner = AiConfigRefiner(analyzer, str(tmp_path / "test.db"), cache_dir=str(tmp_path / "cache"))
        assert refiner._resolve_use_compact(None) is True


class TestTryPromptLevels:
    """Tests for _try_prompt_levels context overflow and error handling."""

    def _patch_messages(self, refiner: AiConfigRefiner) -> Any:
        return patch.object(
            refiner._analyzer,
            "build_initial_messages",
            return_value=[{"role": "system", "content": "s"}],
        )

    def test_returns_config_on_success(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        state = _RetryState()
        with self._patch_messages(refiner):
            config, error = refiner._try_prompt_levels(
                {}, state, use_compact=False, call_fn=lambda msgs: {"name": "users"}
            )
        assert config == {"name": "users"}
        assert error is None

    def test_returns_empty_config_error_on_none_response(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        state = _RetryState()
        with self._patch_messages(refiner):
            config, error = refiner._try_prompt_levels({}, state, use_compact=False, call_fn=lambda msgs: None)
        assert config is None
        assert error is not None
        assert error.error_type == "empty_config"

    def test_returns_empty_config_error_on_empty_dict(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        state = _RetryState()
        with self._patch_messages(refiner):
            config, error = refiner._try_prompt_levels({}, state, use_compact=False, call_fn=lambda msgs: {})
        assert config is None
        assert error is not None
        assert error.error_type == "empty_config"

    def test_context_overflow_falls_back_to_compact_level(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        state = _RetryState()
        call_count = 0

        def call_fn(_msgs: list[dict[str, str]]) -> dict[str, Any] | None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ContextOverflowError("context exceeded")
            return {"name": "users"}

        with self._patch_messages(refiner):
            config, error = refiner._try_prompt_levels({}, state, use_compact=False, call_fn=call_fn)
        assert config == {"name": "users"}
        assert error is None
        assert state.min_prompt_level == 1
        assert call_count == 2

    def test_context_overflow_at_ultra_level_raises(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        state = _RetryState()

        def call_fn(msgs: list[dict[str, str]]) -> dict[str, Any] | None:
            raise ContextOverflowError("context exceeded")

        with self._patch_messages(refiner), pytest.raises(ContextOverflowError):
            refiner._try_prompt_levels({}, state, use_compact=True, call_fn=call_fn)

    def test_value_error_returns_error_summary(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        state = _RetryState()

        def call_fn(msgs: list[dict[str, str]]) -> dict[str, Any] | None:
            raise ValueError("bad value")

        with self._patch_messages(refiner):
            config, error = refiner._try_prompt_levels({}, state, use_compact=False, call_fn=call_fn)
        assert config is None
        assert error is not None

    def test_os_error_returns_error_summary(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        state = _RetryState()

        def call_fn(msgs: list[dict[str, str]]) -> dict[str, Any] | None:
            raise OSError("network error")

        with self._patch_messages(refiner):
            config, error = refiner._try_prompt_levels({}, state, use_compact=False, call_fn=call_fn)
        assert config is None
        assert error is not None

    def test_skips_levels_below_min_prompt_level(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        state = _RetryState()
        state.min_prompt_level = 2  # Skip levels 0 and 1
        call_count = 0

        def call_fn(msgs: list[dict[str, str]]) -> dict[str, Any] | None:
            del msgs
            nonlocal call_count
            call_count += 1
            return {"name": "users"}

        with self._patch_messages(refiner):
            config, _ = refiner._try_prompt_levels({}, state, use_compact=False, call_fn=call_fn)
        assert call_count == 1
        assert config == {"name": "users"}

    def test_returns_none_none_when_all_levels_skipped(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        state = _RetryState()
        state.min_prompt_level = 10  # Skip all levels

        def call_fn(msgs: list[dict[str, str]]) -> dict[str, Any] | None:
            del msgs
            return {"name": "users"}

        with self._patch_messages(refiner):
            config, error = refiner._try_prompt_levels({}, state, use_compact=False, call_fn=call_fn)
        assert config is None
        assert error is None


class TestValidateConfig:
    """Tests for _validate_config covering column_mismatch, empty_config, preview errors."""

    def test_returns_column_mismatch_for_unknown_column(self, tmp_path: Any) -> None:
        db_path = _create_users_db(tmp_path)
        refiner = _make_refiner(tmp_path, db_path=db_path)
        config = {"name": "users", "count": 10, "columns": [{"name": "nonexistent", "generator": "string"}]}
        with DataOrchestrator(db_path) as orch:
            error = refiner._validate_config(orch, "users", config)
        assert error is not None
        assert error.error_type == "column_mismatch"
        assert error.column == "nonexistent"

    def test_returns_empty_config_when_no_columns_suggested(self, tmp_path: Any) -> None:
        db_path = _create_users_db(tmp_path)
        refiner = _make_refiner(tmp_path, db_path=db_path)
        config = {"name": "users", "count": 10, "columns": []}
        with DataOrchestrator(db_path) as orch:
            error = refiner._validate_config(orch, "users", config)
        assert error is not None
        assert error.error_type == "empty_config"

    def test_returns_error_summary_on_preview_failure(self, tmp_path: Any) -> None:
        db_path = _create_users_db(tmp_path)
        refiner = _make_refiner(tmp_path, db_path=db_path)
        config = _valid_users_config()
        with (
            DataOrchestrator(db_path) as orch,
            patch.object(orch, "preview_table", side_effect=RuntimeError("preview failed")),
        ):
            error = refiner._validate_config(orch, "users", config)
        # Strengthened from `assert error is not None` (mutmut weak assertion).
        # Pins the _default_error classification: error_type, message content,
        # and retryable flag. Mutants like `error_type="runtime_error"` →
        # `error_type="XXruntime_errorXX"` or `retryable=not is_infrastructure`
        # → `retryable=is_infrastructure` now get killed.
        assert error is not None
        assert error.error_type == "runtime_error"
        assert "preview failed" in error.message
        assert "RuntimeError" in error.message
        assert error.retryable is True

    def test_returns_none_on_valid_config(self, tmp_path: Any) -> None:
        db_path = _create_users_db(tmp_path)
        refiner = _make_refiner(tmp_path, db_path=db_path)
        config = _valid_users_config()
        with DataOrchestrator(db_path) as orch:
            error = refiner._validate_config(orch, "users", config)
        assert error is None


class TestHandleValidationResult:
    """Tests for _handle_validation_result progress callbacks and state updates."""

    def test_emits_done_progress_on_success(self, tmp_path: Any) -> None:
        db_path = _create_users_db(tmp_path)
        refiner = _make_refiner(tmp_path, db_path=db_path)
        valid_config = _valid_users_config()
        state = _RetryState()
        progress_events: list[tuple[str, dict[str, Any]]] = []
        with DataOrchestrator(db_path) as orch:
            result = refiner._handle_validation_result(
                orch,
                "users",
                "abc",
                valid_config,
                0,
                3,
                state,
                on_progress=lambda p, i: progress_events.append((p, i)),
            )
        assert result == valid_config
        assert ("done", {"tokens": 0, "model": "validated"}) in progress_events

    def test_no_progress_callback_does_not_crash_on_success(self, tmp_path: Any) -> None:
        db_path = _create_users_db(tmp_path)
        refiner = _make_refiner(tmp_path, db_path=db_path)
        valid_config = _valid_users_config()
        state = _RetryState()
        with DataOrchestrator(db_path) as orch:
            result = refiner._handle_validation_result(
                orch,
                "users",
                "abc",
                valid_config,
                0,
                3,
                state,
                on_progress=None,
            )
        assert result == valid_config

    def test_appends_refinement_messages_on_validation_failure(self, tmp_path: Any) -> None:
        db_path = _create_users_db(tmp_path)
        refiner = _make_refiner(tmp_path, db_path=db_path)
        invalid_config = {"name": "users", "count": 10, "columns": [{"name": "nonexistent", "generator": "string"}]}
        state = _RetryState()
        with DataOrchestrator(db_path) as orch:
            result = refiner._handle_validation_result(
                orch,
                "users",
                "abc",
                invalid_config,
                0,
                3,
                state,
                on_progress=None,
            )
        assert result is None
        # Should have appended assistant + user messages for refinement
        assert len(state.messages_history) == 2
        assert state.messages_history[0]["role"] == "assistant"
        assert state.messages_history[1]["role"] == "user"


class TestStreamingRefinement:
    """Tests for generate_and_refine_streaming covering progress and context degradation."""

    def test_streaming_first_attempt_success(self, tmp_path: Any) -> None:
        db_path = _create_users_db(tmp_path)
        refiner = _make_refiner(tmp_path, db_path=db_path)
        valid_config = _valid_users_config()
        with patch.object(refiner._analyzer, "call_llm_streaming", return_value=valid_config):
            result = refiner.generate_and_refine_streaming("users", max_retries=3)
        assert result["name"] == "users"

    def test_streaming_emits_refining_validating_done_progress(self, tmp_path: Any) -> None:
        db_path = _create_users_db(tmp_path)
        refiner = _make_refiner(tmp_path, db_path=db_path)
        valid_config = _valid_users_config()
        progress_events: list[tuple[str, dict[str, Any]]] = []
        with patch.object(refiner._analyzer, "call_llm_streaming", return_value=valid_config):
            refiner.generate_and_refine_streaming(
                "users",
                max_retries=3,
                on_progress=lambda p, i: progress_events.append((p, i)),
            )
        phases = [p for p, _ in progress_events]
        assert "refining" in phases
        assert "validating" in phases
        assert ("done", {"tokens": 0, "model": "validated"}) in progress_events

    def test_streaming_uses_cached_config_with_progress(self, tmp_path: Any) -> None:
        db_path = _create_users_db(tmp_path)
        refiner = _make_refiner(tmp_path, db_path=db_path)
        cached_config = _valid_users_config()
        with DataOrchestrator(db_path) as orch:
            schema_hash = refiner._compute_schema_hash(orch, "users")
        refiner._cache_successful_config("users", cached_config, schema_hash)
        call_count = 0

        def mock_streaming(_msgs: list[dict[str, str]], on_progress: Any = None) -> dict[str, Any]:
            del on_progress
            nonlocal call_count
            call_count += 1
            return cached_config

        progress_events: list[tuple[str, dict[str, Any]]] = []
        with patch.object(refiner._analyzer, "call_llm_streaming", side_effect=mock_streaming):
            result = refiner.generate_and_refine_streaming(
                "users",
                max_retries=3,
                on_progress=lambda p, i: progress_events.append((p, i)),
            )
        assert result["name"] == "users"
        assert call_count == 0  # Cache hit, no LLM call
        assert ("done", {"tokens": 0, "model": "cached"}) in progress_events

    def test_streaming_continues_after_generation_failure(self, tmp_path: Any) -> None:
        db_path = _create_users_db(tmp_path)
        refiner = _make_refiner(tmp_path, db_path=db_path)
        mock_fn, call_log = _make_fail_then_succeed_streaming(
            _valid_users_config(),
            fail_until_call=1,
            error=RuntimeError("LLM temporarily failed"),
        )
        with patch.object(refiner._analyzer, "call_llm_streaming", side_effect=mock_fn):
            result = refiner.generate_and_refine_streaming("users", max_retries=3)
        assert result["name"] == "users"
        assert len(call_log) == 2

    def test_streaming_implements_normal_to_ultra_compact_degradation(self, tmp_path: Any) -> None:
        """Verify normal -> compact -> ultra-compact degradation on context overflow."""
        db_path = _create_users_db(tmp_path)
        refiner = _make_refiner(tmp_path, db_path=db_path)
        mock_fn, call_log = _make_fail_then_succeed_streaming(
            _valid_users_config(),
            fail_until_call=2,
            error=ContextOverflowError("context exceeded"),
        )
        with patch.object(refiner._analyzer, "call_llm_streaming", side_effect=mock_fn):
            result = refiner.generate_and_refine_streaming("users", max_retries=3)
        assert result["name"] == "users"
        # 3 calls: normal overflow, compact overflow, ultra success
        assert len(call_log) == 3


class TestRefinementLoopExhaustion:
    """Tests for _refinement_loop edge cases."""

    def test_raises_unexpected_state_when_all_attempts_return_none(self, tmp_path: Any) -> None:
        db_path = _create_users_db(tmp_path)
        refiner = _make_refiner(tmp_path, db_path=db_path)
        with (
            DataOrchestrator(db_path) as orch,
            patch.object(refiner, "_try_prompt_levels", return_value=(None, None)),
            pytest.raises(AISuggestionFailedError, match="Unexpected state"),
        ):
            refiner._refinement_loop(
                orch,
                "users",
                {},
                "abc",
                max_retries=2,
                no_cache=True,
                use_compact=False,
                call_fn=lambda msgs: None,
            )


class TestCacheErrorHandling:
    """Tests for OSError handling in _cache_successful_config and get_cached_config."""

    def test_cache_successful_config_swallows_oserror(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        # Create a file where cache_dir should be, so mkdir under it fails
        blocker = tmp_path / "cache"
        blocker.write_text("blocker", encoding="utf-8")
        refiner._cache_dir = blocker / "subdir"
        # Should not raise despite OSError
        refiner._cache_successful_config("users", {"name": "users"}, "abc123")

    def test_get_cached_config_returns_dict_without_meta(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        refiner._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = refiner._cache_dir / "users.json"
        cache_file.write_text(json.dumps({"name": "users", "count": 10}), encoding="utf-8")
        result = refiner.get_cached_config("users")
        assert result == {"name": "users", "count": 10}

    def test_get_cached_config_swallows_invalid_json(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        refiner._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = refiner._cache_dir / "users.json"
        cache_file.write_text("{invalid json", encoding="utf-8")
        result = refiner.get_cached_config("users")
        assert result is None

    def test_get_cached_config_swallows_oserror(self, tmp_path: Any) -> None:
        refiner = _make_refiner(tmp_path)
        refiner._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = refiner._cache_dir / "users.json"
        cache_file.write_text("content", encoding="utf-8")
        with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
            result = refiner.get_cached_config("users")
        assert result is None


class TestCriticalConstraints:
    """Verify critical constraints from project_memory.md."""

    def test_non_retryable_errors_includes_json_syntax_not_invalid_json(self) -> None:
        assert "json_syntax" in AiConfigRefiner._NON_RETRYABLE_ERRORS
        assert "invalid_json" not in AiConfigRefiner._NON_RETRYABLE_ERRORS

    def test_ultra_compact_prompt_excludes_pk_default_unique_check(self) -> None:
        prompt_upper = _ULTRA_COMPACT_SYSTEM_PROMPT.upper()
        assert "PRIMARY KEY" in prompt_upper
        assert "AUTOINCREMENT" in prompt_upper
        assert "DEFAULT" in prompt_upper
        assert "UNIQUE" in prompt_upper
        assert "CHECK" in prompt_upper

    def test_compact_prompt_skips_few_shot_examples(self) -> None:
        analyzer = SchemaAnalyzer(config=AIConfig(api_key="test-key", model="test-model"))
        schema_ctx = {
            "table_name": "t",
            "columns": [],
            "indexes": [],
            "foreign_keys": [],
            "all_table_names": [],
            "sample_data": [],
            "dialect": "sqlite",
        }
        full_msgs = analyzer.build_initial_messages(schema_ctx)
        compact_msgs = analyzer.build_initial_messages(schema_ctx, compact=True)
        ultra_msgs = analyzer.build_initial_messages(schema_ctx, ultra_compact=True)
        # Full: system + examples + user. Compact/Ultra: system + user only.
        assert len(compact_msgs) < len(full_msgs)
        assert len(ultra_msgs) < len(full_msgs)
        assert len(compact_msgs) == len(ultra_msgs) == 2
