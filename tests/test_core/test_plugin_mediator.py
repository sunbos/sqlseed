"""Tests for the non-AI plugin mediation path.

AI suggestion mediation (``apply_ai_suggestions`` and its helpers) was
moved to ``sqlseed_ai.ai_mediator`` per ARCHITECTURE.md Section 7.6.
Tests for the AI path live in ``plugins/sqlseed-ai/tests/test_ai_mediator.py``.
This file covers what remains in core:
* ``apply_template_pool`` (calls ``sqlseed_pre_generate_templates`` hook)
* ``apply_batch_transforms`` (calls ``sqlseed_transform_batch`` hook)
* ``_iter_template_eligible_specs`` filtering
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from sqlseed.core.mapper import GeneratorSpec
from sqlseed.core.plugin_mediator import PluginMediator

# Import the shared ColumnInfo factory from tests.conftest to avoid
# CodeDuplication with test_unique_adjuster.py (both files previously
# defined an identical _make_col_info helper).
from tests.conftest import make_col_info_varchar as _make_col_info


def _make_mock_mediator() -> PluginMediator:
    """PluginMediator with all-MagicMock dependencies.

    Extracted to avoid CodeDuplication across the 7+ tests that bootstrap
    an identical no-op mediator for filter-checking tests.
    """
    return PluginMediator(plugins=MagicMock(), db=MagicMock(), schema=MagicMock())


def _make_mock_mediator_with_template_hook(
    template_return: Any, sample_rows: Any = None, sample_rows_error: Exception | None = None
) -> PluginMediator:
    """PluginMediator whose template hook returns ``template_return``.

    Extracted to avoid CodeDuplication across the 4 apply_template_pool
    tests that all wire up a MagicMock plugins/db/schema trio with only
    the hook return value differing.
    """
    db = MagicMock()
    if sample_rows_error is not None:
        db.get_sample_rows.side_effect = sample_rows_error
    else:
        db.get_sample_rows.return_value = sample_rows if sample_rows is not None else []

    plugins = MagicMock()
    plugins.hook.sqlseed_pre_generate_templates.return_value = template_return

    return PluginMediator(plugins=plugins, db=db, schema=MagicMock())


def _make_string_name_specs() -> tuple[list[Any], dict[str, GeneratorSpec]]:
    """Common ``(col_infos, specs)`` for a string 'name' column.

    Extracted to avoid CodeDuplication across the 5+ tests that all set
    up an identical string 'name' column for template-pool / filter tests.
    """
    return [_make_col_info("name", "VARCHAR(50)")], {"name": GeneratorSpec(generator_name="string")}


class TestPluginMediator:
    def test_apply_batch_transforms_no_hooks(self, mediator_ctx) -> None:
        batch = [{"name": "alice"}, {"name": "bob"}]
        result = mediator_ctx.mediator.apply_batch_transforms("t", batch)
        assert result == batch

    def test_apply_template_pool_no_hooks(self, mediator_ctx) -> None:
        specs = {"name": GeneratorSpec(generator_name="string")}
        result = mediator_ctx.mediator.apply_template_pool("t", mediator_ctx.schema.get_column_info("t"), specs, 10)
        assert result["name"].generator_name == "string"


class TestIterTemplateEligibleSpecs:
    """Tests for _iter_template_eligible_specs filtering.

    Parametrized to cover all skip-rules (PK, autoincrement, default,
    non-string generator, configured, unique) plus the positive yield
    case. Each case is a (col_name, col_type, generator, default, is_pk,
    is_auto, configured, unique_cols, expected_count) tuple.
    """

    @pytest.mark.parametrize(
        ("col_name", "col_type", "generator", "default", "is_pk", "is_auto", "configured", "unique_cols", "expected"),
        [
            pytest.param("id", "VARCHAR(50)", "string", None, True, False, set(), set(), 0, id="skips_primary_key"),
            pytest.param("id", "INTEGER", "string", None, False, True, set(), set(), 0, id="skips_autoincrement"),
            pytest.param(
                "status", "VARCHAR(50)", "string", "active", False, False, set(), set(), 0, id="skips_default"
            ),
            pytest.param("count", "INTEGER", "integer", None, False, False, set(), set(), 0, id="skips_non_string"),
            pytest.param(
                "name", "VARCHAR(50)", "string", None, False, False, {"name"}, set(), 0, id="skips_configured"
            ),
            pytest.param("code", "VARCHAR(50)", "string", None, False, False, set(), {"code"}, 0, id="skips_unique"),
            pytest.param("name", "VARCHAR(50)", "string", None, False, False, set(), set(), 1, id="yields_eligible"),
        ],
    )
    def test_iter_template_eligible_specs_filtering(
        self,
        col_name: str,
        col_type: str,
        generator: str,
        default: Any,
        is_pk: bool,
        is_auto: bool,
        configured: set[str],
        unique_cols: set[str],
        expected: int,
    ) -> None:
        mediator = _make_mock_mediator()
        specs = {col_name: GeneratorSpec(generator_name=generator)}
        col_infos = [
            _make_col_info(col_name, col_type, default=default, is_primary_key=is_pk, is_autoincrement=is_auto)
        ]
        eligible = list(
            mediator._iter_template_eligible_specs(specs, col_infos, configured, unique_columns=unique_cols)
        )
        assert len(eligible) == expected
        if expected == 1:
            assert eligible[0][0] == col_name


class TestApplyTemplatePool:
    """Tests for apply_template_pool mutation."""

    def test_returns_unchanged_when_no_eligible_cols(self) -> None:
        mediator = _make_mock_mediator()
        # All columns are integer (not string) → no eligible cols
        col_infos = [_make_col_info("count", "INTEGER")]
        specs = {"count": GeneratorSpec(generator_name="integer")}
        result = mediator.apply_template_pool("t", col_infos, specs, 100)
        assert result["count"].generator_name == "integer"

    def test_applies_template_when_hook_returns_values(self) -> None:
        mediator = _make_mock_mediator_with_template_hook(
            template_return=["Alice", "Bob", "Charlie"],
            sample_rows=[{"name": "Alice"}, {"name": "Bob"}],
        )
        col_infos, specs = _make_string_name_specs()
        result = mediator.apply_template_pool("t", col_infos, specs, 100)

        # Should be replaced with foreign_key template pool
        assert result["name"].generator_name == "foreign_key"
        assert result["name"].params["ref_table"] == "__template_pool__"
        assert result["name"].params["_ref_values"] == ["Alice", "Bob", "Charlie"]

    @pytest.mark.parametrize(
        ("template_return", "sample_rows"),
        [
            pytest.param([], [], id="empty_list"),
            pytest.param(None, [], id="none_value"),
        ],
    )
    def test_returns_unchanged_when_hook_returns_empty_or_none(
        self, template_return: Any, sample_rows: list[Any]
    ) -> None:
        """Hook returning [] or None should leave the string generator unchanged."""
        mediator = _make_mock_mediator_with_template_hook(template_return=template_return, sample_rows=sample_rows)
        col_infos, specs = _make_string_name_specs()
        result = mediator.apply_template_pool("t", col_infos, specs, 100)
        assert result["name"].generator_name == "string"

    def test_handles_sample_rows_error_gracefully(self) -> None:
        # When db.get_sample_rows raises, should continue with empty sample_rows
        mediator = _make_mock_mediator_with_template_hook(
            template_return=["template1"],
            sample_rows_error=RuntimeError("DB error"),
        )
        col_infos, specs = _make_string_name_specs()
        result = mediator.apply_template_pool("t", col_infos, specs, 100)
        # Should still apply template despite sample_rows error
        assert result["name"].generator_name == "foreign_key"
        assert result["name"].params["_ref_values"] == ["template1"]


class TestApplyBatchTransforms:
    """Tests for apply_batch_transforms with hook results."""

    @pytest.mark.parametrize(
        "hook_return",
        [
            pytest.param([], id="no_results"),
            pytest.param([None, None], id="all_none"),
        ],
    )
    def test_returns_original_batch_when_no_results_or_all_none(self, hook_return: list[Any]) -> None:
        """Empty results or all-None results should return the original batch."""
        plugins = MagicMock()
        plugins.hook.sqlseed_transform_batch.return_value = hook_return

        mediator = PluginMediator(plugins=plugins, db=MagicMock(), schema=MagicMock())
        batch = [{"name": "alice"}]
        result = mediator.apply_batch_transforms("t", batch)
        assert result == batch

    def test_returns_last_non_none_result(self) -> None:
        plugins = MagicMock()
        plugins.hook.sqlseed_transform_batch.return_value = [
            [{"name": "transformed1"}],
            None,
            [{"name": "transformed2"}],
        ]

        mediator = PluginMediator(plugins=plugins, db=MagicMock(), schema=MagicMock())
        batch = [{"name": "alice"}]
        result = mediator.apply_batch_transforms("t", batch)
        # Last non-None result wins
        assert result == [{"name": "transformed2"}]
