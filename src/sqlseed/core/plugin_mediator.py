from __future__ import annotations

import contextlib
import sqlite3
from typing import TYPE_CHECKING, Any, ClassVar

from sqlseed._utils.logger import get_logger
from sqlseed.core.mapper import GeneratorSpec

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlseed.core.schema import SchemaInferrer
    from sqlseed.database._protocol import DatabaseAdapter
    from sqlseed.plugins.manager import PluginManager

logger = get_logger(__name__)


class PluginMediator:
    AI_APPLICABLE_GENERATORS: ClassVar[frozenset[str]] = frozenset({"string"})

    def __init__(
        self,
        plugins: PluginManager,
        db: DatabaseAdapter,
        schema: SchemaInferrer,
    ) -> None:
        self._plugins = plugins
        self._db = db
        self._schema = schema

    def _has_unmatched_cols(self, column_infos: list[Any], specs: dict[str, GeneratorSpec]) -> bool:
        return any(
            specs.get(col.name) is not None
            and specs[col.name].generator_name in self.AI_APPLICABLE_GENERATORS
            and not col.is_primary_key
            and not col.is_autoincrement
            and col.default is None
            for col in column_infos
        )

    def _process_single_ai_column(self, col_cfg: dict[str, Any], specs: dict[str, GeneratorSpec]) -> None:
        col_name = col_cfg.get("name")
        if not col_name or col_name not in specs:
            return

        gen = col_cfg.get("generator")
        if not gen or gen == "skip":
            return

        derive_from = col_cfg.get("derive_from")
        expression = col_cfg.get("expression")

        if derive_from and expression:
            specs[col_name] = GeneratorSpec(
                generator_name="__derive__",
                params={"derive_from": derive_from, "expression": expression},
            )
        else:
            params = col_cfg.get("params", {})
            if isinstance(params, dict):
                specs[col_name] = GeneratorSpec(
                    generator_name=gen,
                    params=params,
                    native_faker_method=col_cfg.get("faker_method"),
                    native_mimesis_method=col_cfg.get("mimesis_method"),
                    native_params=col_cfg.get("native_params"),
                )

    def _process_ai_result(
        self,
        ai_result: Any,
        specs: dict[str, GeneratorSpec],
        configured: set[str] | None = None,
    ) -> None:
        if not ai_result or not isinstance(ai_result, dict):
            return

        skip = configured or set()
        ai_columns = ai_result.get("columns", [])
        if not isinstance(ai_columns, list):
            return

        for col_cfg in ai_columns:
            if isinstance(col_cfg, dict):
                col_name = col_cfg.get("name")
                if col_name and col_name in skip:
                    continue
                self._process_single_ai_column(col_cfg, specs)

    def apply_ai_suggestions(
        self,
        table_name: str,
        column_infos: list[Any],
        specs: dict[str, GeneratorSpec],
        user_configured_columns: set[str] | None = None,
    ) -> dict[str, GeneratorSpec]:
        if not self._has_unmatched_cols(column_infos, specs):
            return specs

        try:
            fks = self._db.get_foreign_keys(table_name)
            all_tables = self._db.get_table_names()
            indexes = self._schema.get_index_info(table_name)
            sample_data = self._schema.get_sample_data(table_name, limit=5)

            ai_result = self._plugins.hook.sqlseed_ai_analyze_table(
                table_name=table_name,
                columns=column_infos,
                indexes=[{"name": i.name, "columns": i.columns, "unique": i.unique} for i in indexes],
                sample_data=sample_data,
                foreign_keys=fks,
                all_table_names=all_tables,
            )

            configured = user_configured_columns or set()
            self._process_ai_result(ai_result, specs, configured)

        except (ValueError, RuntimeError, ImportError) as e:
            logger.debug("AI suggestions not available", table_name=table_name, error=str(e))

        return specs

    def _iter_template_eligible_specs(
        self,
        specs: dict[str, GeneratorSpec],
        column_infos: list[Any],
        configured: set[str],
    ) -> Iterator[tuple[str, GeneratorSpec, Any]]:
        for col_name, spec in list(specs.items()):
            if spec.generator_name != "string":
                continue
            if col_name in configured:
                continue
            col_info = next((c for c in column_infos if c.name == col_name), None)
            if col_info is None or col_info.is_primary_key or col_info.is_autoincrement:
                continue
            if col_info.default is not None:
                continue
            yield col_name, spec, col_info

    def apply_template_pool(
        self,
        table_name: str,
        column_infos: list[Any],
        specs: dict[str, GeneratorSpec],
        count: int,
        user_configured_columns: set[str] | None = None,
    ) -> dict[str, GeneratorSpec]:
        configured = user_configured_columns or set()
        needs_template = any(True for _ in self._iter_template_eligible_specs(specs, column_infos, configured))
        if not needs_template:
            return specs
        for col_name, _spec, col_info in self._iter_template_eligible_specs(specs, column_infos, configured):
            sample_data_for_col: list[Any] = []
            with contextlib.suppress(ValueError, OSError, RuntimeError, sqlite3.OperationalError):
                sample_data_for_col = self._db.get_column_values(table_name, col_name, limit=10)

            template_values = self._plugins.hook.sqlseed_pre_generate_templates(
                table_name=table_name,
                column_name=col_name,
                column_type=col_info.type,
                count=min(count, 50),
                sample_data=sample_data_for_col,
            )
            if template_values:
                specs[col_name] = GeneratorSpec(
                    generator_name="foreign_key",
                    params={
                        "ref_table": "__template_pool__",
                        "ref_column": col_name,
                        "strategy": "random",
                        "_ref_values": template_values,
                    },
                )
        return specs

    def apply_batch_transforms(
        self,
        table_name: str,
        batch: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        results = self._plugins.hook.sqlseed_transform_batch(
            table_name=table_name,
            batch=batch,
        )
        current = batch
        if results:
            for r in results:
                if r is not None:
                    current = r
        return current
