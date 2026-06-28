"""Tests for the AI suggestion mediator (moved from core ``plugin_mediator``).

Covers ``sqlseed_ai.ai_mediator``:
* ``AI_APPLICABLE_GENERATORS`` constant
* ``_process_single_ai_column`` — single AI col_cfg → GeneratorSpec merge
* ``_process_ai_result`` — full AI result dict → specs merge
* ``_build_ai_context`` — db/schema → context dict (with error suppression)
* ``apply_ai_suggestions`` — top-level orchestration (unmatched check,
  context build, analyze_fn call, result merge)

The ``analyze_fn`` callable is mocked (no real LLM call), but the
db/schema interaction in ``_build_ai_context`` and
``apply_ai_suggestions`` uses the real ``RawSQLiteAdapter`` /
``SchemaInferrer`` from ``mediator_ctx`` so method-name drift or
return-type mismatch gets caught.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from sqlseed_ai.ai_mediator import (
    AI_APPLICABLE_GENERATORS,
    _build_ai_context,
    _has_unmatched_cols,
    _process_ai_result,
    _process_single_ai_column,
    apply_ai_suggestions,
)

from sqlseed.core.mapper import GeneratorSpec
from sqlseed.database._protocol import ColumnInfo


def _make_col_info(
    name: str,
    col_type: str = "VARCHAR(50)",
    *,
    nullable: bool = True,
    default: Any = None,
    is_primary_key: bool = False,
    is_autoincrement: bool = False,
) -> ColumnInfo:
    """Factory to create ColumnInfo for tests."""
    return ColumnInfo(
        name=name,
        type=col_type,
        nullable=nullable,
        default=default,
        is_primary_key=is_primary_key,
        is_autoincrement=is_autoincrement,
    )


# ---------------------------------------------------------------------------
# AI_APPLICABLE_GENERATORS constant
# ---------------------------------------------------------------------------


class TestAiApplicableGenerators:
    def test_is_frozenset(self) -> None:
        assert isinstance(AI_APPLICABLE_GENERATORS, frozenset)

    def test_contains_string(self) -> None:
        assert "string" in AI_APPLICABLE_GENERATORS

    def test_does_not_contain_integer(self) -> None:
        assert "integer" not in AI_APPLICABLE_GENERATORS

    def test_does_not_contain_email(self) -> None:
        assert "email" not in AI_APPLICABLE_GENERATORS


# ---------------------------------------------------------------------------
# _has_unmatched_cols
# ---------------------------------------------------------------------------


class TestHasUnmatchedCols:
    def test_returns_false_when_no_ai_applicable_cols(self) -> None:
        col_infos = [_make_col_info("name", "VARCHAR(50)")]
        specs = {"name": GeneratorSpec(generator_name="email")}
        assert _has_unmatched_cols(col_infos, specs) is False

    def test_returns_true_when_string_col_without_default(self) -> None:
        col_infos = [_make_col_info("name", "VARCHAR(50)")]
        specs = {"name": GeneratorSpec(generator_name="string")}
        assert _has_unmatched_cols(col_infos, specs) is True

    def test_returns_false_when_string_col_has_default(self) -> None:
        col_infos = [_make_col_info("status", "VARCHAR(50)", default="active")]
        specs = {"status": GeneratorSpec(generator_name="string")}
        assert _has_unmatched_cols(col_infos, specs) is False

    def test_returns_false_when_string_col_is_primary_key(self) -> None:
        col_infos = [_make_col_info("id", "VARCHAR(50)", is_primary_key=True)]
        specs = {"id": GeneratorSpec(generator_name="string")}
        assert _has_unmatched_cols(col_infos, specs) is False

    def test_returns_false_when_string_col_is_autoincrement(self) -> None:
        col_infos = [_make_col_info("id", "INTEGER", is_autoincrement=True)]
        specs = {"id": GeneratorSpec(generator_name="string")}
        assert _has_unmatched_cols(col_infos, specs) is False


# ---------------------------------------------------------------------------
# _process_single_ai_column
# ---------------------------------------------------------------------------


class TestProcessSingleAiColumn:
    def test_skips_when_no_name(self) -> None:
        specs: dict[str, GeneratorSpec] = {}
        _process_single_ai_column({}, specs)
        assert specs == {}

    def test_skips_when_name_not_in_specs(self) -> None:
        specs: dict[str, GeneratorSpec] = {}
        _process_single_ai_column({"name": "unknown"}, specs)
        assert specs == {}

    def test_skips_when_no_generator(self) -> None:
        specs = {"col": GeneratorSpec(generator_name="string")}
        _process_single_ai_column({"name": "col"}, specs)
        # Spec unchanged
        assert specs["col"].generator_name == "string"

    def test_skips_when_generator_is_skip(self) -> None:
        specs = {"col": GeneratorSpec(generator_name="string")}
        _process_single_ai_column({"name": "col", "generator": "skip"}, specs)
        assert specs["col"].generator_name == "string"

    def test_processes_derived_column(self) -> None:
        specs = {"col": GeneratorSpec(generator_name="string")}
        col_cfg = {
            "name": "col",
            "generator": "string",
            "derive_from": ["src"],
            "expression": "value + 1",
        }
        _process_single_ai_column(col_cfg, specs)
        assert specs["col"].generator_name == "__derive__"
        assert specs["col"].params == {"derive_from": ["src"], "expression": "value + 1"}

    def test_processes_regular_generator_with_params(self) -> None:
        specs = {"col": GeneratorSpec(generator_name="string")}
        col_cfg = {
            "name": "col",
            "generator": "email",
            "params": {"domain": "test.com"},
        }
        _process_single_ai_column(col_cfg, specs)
        assert specs["col"].generator_name == "email"
        assert specs["col"].params == {"domain": "test.com"}

    def test_processes_with_native_methods(self) -> None:
        specs = {"col": GeneratorSpec(generator_name="string")}
        col_cfg = {
            "name": "col",
            "generator": "string",
            "params": {"min_length": 5},
            "faker_method": "email",
            "mimesis_method": "person.full_name",
            "native_params": {"domain": "test.com"},
        }
        _process_single_ai_column(col_cfg, specs)
        assert specs["col"].native_faker_method == "email"
        assert specs["col"].native_mimesis_method == "person.full_name"
        assert specs["col"].native_params == {"domain": "test.com"}

    def test_skips_non_dict_params(self) -> None:
        specs = {"col": GeneratorSpec(generator_name="string")}
        col_cfg = {
            "name": "col",
            "generator": "email",
            "params": "not_a_dict",  # Non-dict params should be ignored
        }
        _process_single_ai_column(col_cfg, specs)
        # Spec unchanged because params was not a dict
        assert specs["col"].generator_name == "string"


# ---------------------------------------------------------------------------
# _process_ai_result
# ---------------------------------------------------------------------------


class TestProcessAiResult:
    def test_returns_unchanged_when_ai_result_is_none(self) -> None:
        specs = {"col": GeneratorSpec(generator_name="string")}
        _process_ai_result(None, specs)
        assert specs["col"].generator_name == "string"

    def test_returns_unchanged_when_ai_result_not_dict(self) -> None:
        specs = {"col": GeneratorSpec(generator_name="string")}
        _process_ai_result("not_a_dict", specs)
        assert specs["col"].generator_name == "string"

    def test_returns_unchanged_when_columns_not_list(self) -> None:
        specs = {"col": GeneratorSpec(generator_name="string")}
        _process_ai_result({"columns": "not_a_list"}, specs)
        assert specs["col"].generator_name == "string"

    def test_processes_valid_ai_result(self) -> None:
        specs = {"col": GeneratorSpec(generator_name="string")}
        ai_result = {
            "columns": [
                {"name": "col", "generator": "email", "params": {"domain": "test.com"}},
            ]
        }
        _process_ai_result(ai_result, specs)
        assert specs["col"].generator_name == "email"

    def test_skips_configured_columns(self) -> None:
        specs = {"col": GeneratorSpec(generator_name="string")}
        ai_result = {
            "columns": [
                {"name": "col", "generator": "email"},
            ]
        }
        _process_ai_result(ai_result, specs, configured={"col"})
        # Should be skipped because "col" is in configured set
        assert specs["col"].generator_name == "string"

    def test_skips_non_dict_column_entries(self) -> None:
        specs = {"col": GeneratorSpec(generator_name="string")}
        ai_result = {
            "columns": ["not_a_dict", 42, {"name": "col", "generator": "email"}],
        }
        _process_ai_result(ai_result, specs)
        # Only the dict entry should be processed
        assert specs["col"].generator_name == "email"


# ---------------------------------------------------------------------------
# _build_ai_context
# ---------------------------------------------------------------------------


class TestBuildAiContext:
    def test_returns_none_on_database_error(self) -> None:
        # When db.get_foreign_keys raises, _build_ai_context should return None
        db = MagicMock()
        db.get_foreign_keys.side_effect = RuntimeError("DB error")
        schema = MagicMock()
        result = _build_ai_context(db, schema, "test_table")
        assert result is None

    def test_returns_none_on_oserror(self) -> None:
        db = MagicMock()
        db.get_foreign_keys.side_effect = OSError("OS error")
        schema = MagicMock()
        result = _build_ai_context(db, schema, "test_table")
        assert result is None

    def test_returns_none_on_value_error(self) -> None:
        db = MagicMock()
        db.get_foreign_keys.side_effect = ValueError("bad value")
        schema = MagicMock()
        result = _build_ai_context(db, schema, "test_table")
        assert result is None

    def test_returns_context_on_success(self, mediator_ctx) -> None:
        """_build_ai_context returns real schema data from adapter/schema.

        Previously mocked db.get_foreign_keys/get_table_names and
        schema.get_index_info/get_sample_data, which made the test
        self-proving: the assertions merely echoed the mock return
        values. Now uses the real ``RawSQLiteAdapter`` +
        ``SchemaInferrer`` from ``mediator_ctx`` (table ``t`` with
        columns id+name), so ``_build_ai_context`` actually queries the
        schema. If the adapter/schema method names drift, this test
        fails.
        """
        result = _build_ai_context(mediator_ctx.adapter, mediator_ctx.schema, "t")
        assert result is not None
        # Real schema: table "t" has no FKs; table_names includes "t"
        assert result["foreign_keys"] == []
        assert "t" in result["all_table_names"]
        assert isinstance(result["indexes"], list)
        assert isinstance(result["sample_data"], list)


# ---------------------------------------------------------------------------
# apply_ai_suggestions
# ---------------------------------------------------------------------------


class TestApplyAiSuggestions:
    """Tests for apply_ai_suggestions early returns and full path."""

    def test_returns_unchanged_when_no_unmatched_cols(self) -> None:
        # When no AI-applicable columns, should return specs unchanged
        db = MagicMock()
        schema = MagicMock()
        analyze_fn = MagicMock()
        col_infos = [_make_col_info("name", "VARCHAR(50)")]
        specs = {"name": GeneratorSpec(generator_name="email")}
        result = apply_ai_suggestions(
            analyze_fn=analyze_fn,
            db=db,
            schema=schema,
            table_name="t",
            column_infos=col_infos,
            specs=specs,
        )
        assert result["name"].generator_name == "email"
        # analyze_fn should not be called when no unmatched cols
        analyze_fn.assert_not_called()

    def test_returns_unchanged_when_context_build_fails(self) -> None:
        # When _build_ai_context returns None, should return specs unchanged
        db = MagicMock()
        db.get_foreign_keys.side_effect = RuntimeError("fail")
        schema = MagicMock()
        analyze_fn = MagicMock()
        col_infos = [_make_col_info("name", "VARCHAR(50)")]
        specs = {"name": GeneratorSpec(generator_name="string")}
        result = apply_ai_suggestions(
            analyze_fn=analyze_fn,
            db=db,
            schema=schema,
            table_name="t",
            column_infos=col_infos,
            specs=specs,
        )
        assert result["name"].generator_name == "string"
        # analyze_fn should not be called when context build fails
        analyze_fn.assert_not_called()

    def test_applies_ai_suggestion_when_unmatched_col_exists(self, mediator_ctx) -> None:
        """Full path: unmatched string col → build context → call analyze_fn → process result.

        Uses real adapter/schema from ``mediator_ctx`` (table ``t`` with
        columns id+name) so ``_build_ai_context`` runs against real
        schema. The ``analyze_fn`` callable is mocked because no real
        AI plugin is invoked here — but the db/schema interaction is
        real, so method-name drift or return-type mismatch gets caught.
        """
        analyze_fn = MagicMock(
            return_value={
                "columns": [
                    {"name": "name", "generator": "email"},
                ]
            }
        )
        # Real column info from the schema (table "t" has: id, name)
        col_infos = mediator_ctx.schema.get_column_info("t")
        specs = {"name": GeneratorSpec(generator_name="string")}
        result = apply_ai_suggestions(
            analyze_fn=analyze_fn,
            db=mediator_ctx.adapter,
            schema=mediator_ctx.schema,
            table_name="t",
            column_infos=col_infos,
            specs=specs,
        )
        # AI suggestion should have been applied: "name" col → "email" generator
        assert result["name"].generator_name == "email"
        analyze_fn.assert_called_once()
