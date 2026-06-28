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

from sqlseed.core.mapper import GeneratorSpec
from sqlseed.core.plugin_mediator import PluginMediator
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
    """Tests for _iter_template_eligible_specs filtering."""

    def test_skips_primary_key_columns(self) -> None:
        mediator = PluginMediator(
            plugins=MagicMock(),
            db=MagicMock(),
            schema=MagicMock(),
        )
        specs = {"id": GeneratorSpec(generator_name="string")}
        col_infos = [_make_col_info("id", "VARCHAR(50)", is_primary_key=True)]
        eligible = list(mediator._iter_template_eligible_specs(specs, col_infos, set()))
        assert len(eligible) == 0

    def test_skips_autoincrement_columns(self) -> None:
        mediator = PluginMediator(
            plugins=MagicMock(),
            db=MagicMock(),
            schema=MagicMock(),
        )
        specs = {"id": GeneratorSpec(generator_name="string")}
        col_infos = [_make_col_info("id", "INTEGER", is_autoincrement=True)]
        eligible = list(mediator._iter_template_eligible_specs(specs, col_infos, set()))
        assert len(eligible) == 0

    def test_skips_columns_with_default_values(self) -> None:
        mediator = PluginMediator(
            plugins=MagicMock(),
            db=MagicMock(),
            schema=MagicMock(),
        )
        specs = {"status": GeneratorSpec(generator_name="string")}
        col_infos = [_make_col_info("status", "VARCHAR(50)", default="active")]
        eligible = list(mediator._iter_template_eligible_specs(specs, col_infos, set()))
        assert len(eligible) == 0

    def test_skips_non_string_generators(self) -> None:
        mediator = PluginMediator(
            plugins=MagicMock(),
            db=MagicMock(),
            schema=MagicMock(),
        )
        specs = {"count": GeneratorSpec(generator_name="integer")}
        col_infos = [_make_col_info("count", "INTEGER")]
        eligible = list(mediator._iter_template_eligible_specs(specs, col_infos, set()))
        assert len(eligible) == 0

    def test_skips_configured_columns(self) -> None:
        mediator = PluginMediator(
            plugins=MagicMock(),
            db=MagicMock(),
            schema=MagicMock(),
        )
        specs = {"name": GeneratorSpec(generator_name="string")}
        col_infos = [_make_col_info("name", "VARCHAR(50)")]
        eligible = list(mediator._iter_template_eligible_specs(specs, col_infos, {"name"}))
        assert len(eligible) == 0

    def test_skips_unique_columns(self) -> None:
        mediator = PluginMediator(
            plugins=MagicMock(),
            db=MagicMock(),
            schema=MagicMock(),
        )
        specs = {"code": GeneratorSpec(generator_name="string")}
        col_infos = [_make_col_info("code", "VARCHAR(50)")]
        eligible = list(mediator._iter_template_eligible_specs(specs, col_infos, set(), unique_columns={"code"}))
        assert len(eligible) == 0

    def test_yields_eligible_column(self) -> None:
        mediator = PluginMediator(
            plugins=MagicMock(),
            db=MagicMock(),
            schema=MagicMock(),
        )
        specs = {"name": GeneratorSpec(generator_name="string")}
        col_infos = [_make_col_info("name", "VARCHAR(50)")]
        eligible = list(mediator._iter_template_eligible_specs(specs, col_infos, set()))
        assert len(eligible) == 1
        assert eligible[0][0] == "name"


class TestApplyTemplatePool:
    """Tests for apply_template_pool mutation."""

    def test_returns_unchanged_when_no_eligible_cols(self) -> None:
        mediator = PluginMediator(
            plugins=MagicMock(),
            db=MagicMock(),
            schema=MagicMock(),
        )
        # All columns are integer (not string) → no eligible cols
        col_infos = [_make_col_info("count", "INTEGER")]
        specs = {"count": GeneratorSpec(generator_name="integer")}
        result = mediator.apply_template_pool("t", col_infos, specs, 100)
        assert result["count"].generator_name == "integer"

    def test_applies_template_when_hook_returns_values(self) -> None:
        db = MagicMock()
        db.get_sample_rows.return_value = [{"name": "Alice"}, {"name": "Bob"}]

        plugins = MagicMock()
        plugins.hook.sqlseed_pre_generate_templates.return_value = ["Alice", "Bob", "Charlie"]

        mediator = PluginMediator(plugins=plugins, db=db, schema=MagicMock())
        col_infos = [_make_col_info("name", "VARCHAR(50)")]
        specs = {"name": GeneratorSpec(generator_name="string")}
        result = mediator.apply_template_pool("t", col_infos, specs, 100)

        # Should be replaced with foreign_key template pool
        assert result["name"].generator_name == "foreign_key"
        assert result["name"].params["ref_table"] == "__template_pool__"
        assert result["name"].params["_ref_values"] == ["Alice", "Bob", "Charlie"]

    def test_returns_unchanged_when_hook_returns_empty(self) -> None:
        db = MagicMock()
        db.get_sample_rows.return_value = []

        plugins = MagicMock()
        plugins.hook.sqlseed_pre_generate_templates.return_value = []

        mediator = PluginMediator(plugins=plugins, db=db, schema=MagicMock())
        col_infos = [_make_col_info("name", "VARCHAR(50)")]
        specs = {"name": GeneratorSpec(generator_name="string")}
        result = mediator.apply_template_pool("t", col_infos, specs, 100)
        # Should remain string
        assert result["name"].generator_name == "string"

    def test_returns_unchanged_when_hook_returns_none(self) -> None:
        db = MagicMock()
        db.get_sample_rows.return_value = []

        plugins = MagicMock()
        plugins.hook.sqlseed_pre_generate_templates.return_value = None

        mediator = PluginMediator(plugins=plugins, db=db, schema=MagicMock())
        col_infos = [_make_col_info("name", "VARCHAR(50)")]
        specs = {"name": GeneratorSpec(generator_name="string")}
        result = mediator.apply_template_pool("t", col_infos, specs, 100)
        assert result["name"].generator_name == "string"

    def test_handles_sample_rows_error_gracefully(self) -> None:
        # When db.get_sample_rows raises, should continue with empty sample_rows
        db = MagicMock()
        db.get_sample_rows.side_effect = RuntimeError("DB error")

        plugins = MagicMock()
        plugins.hook.sqlseed_pre_generate_templates.return_value = ["template1"]

        mediator = PluginMediator(plugins=plugins, db=db, schema=MagicMock())
        col_infos = [_make_col_info("name", "VARCHAR(50)")]
        specs = {"name": GeneratorSpec(generator_name="string")}
        result = mediator.apply_template_pool("t", col_infos, specs, 100)
        # Should still apply template despite sample_rows error
        assert result["name"].generator_name == "foreign_key"
        assert result["name"].params["_ref_values"] == ["template1"]


class TestApplyBatchTransforms:
    """Tests for apply_batch_transforms with hook results."""

    def test_returns_original_batch_when_no_results(self) -> None:
        plugins = MagicMock()
        plugins.hook.sqlseed_transform_batch.return_value = []

        mediator = PluginMediator(plugins=plugins, db=MagicMock(), schema=MagicMock())
        batch = [{"name": "alice"}]
        result = mediator.apply_batch_transforms("t", batch)
        assert result == batch

    def test_returns_original_batch_when_all_none(self) -> None:
        plugins = MagicMock()
        plugins.hook.sqlseed_transform_batch.return_value = [None, None]

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
