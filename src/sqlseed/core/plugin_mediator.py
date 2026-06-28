"""Plugin mediator — bridges core orchestrator and pluggy plugin hooks.

The mediator is the single call-site through which the orchestrator
invokes pluggy hooks for batch transforms and template-pool enrichment.

AI-specific mediation (``apply_ai_suggestions``) was moved to
``sqlseed_ai.ai_mediator`` per ARCHITECTURE.md Section 7.6 ("Only
AI-specific mediation moves out"). The orchestrator now invokes the
AI path directly via the ``sqlseed_apply_ai_suggestions`` pluggy hook
(see ``core.orchestrator._specs``), so this module no longer touches
the AI path.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import OperationalError as SAOperationalError

from sqlseed._utils.logger import get_logger
from sqlseed.core.mapper import GeneratorSpec

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlseed.core.schema import SchemaInferrer
    from sqlseed.database._protocol import DatabaseAdapter
    from sqlseed.plugins.manager import PluginManager

logger = get_logger(__name__)


class PluginMediator:
    """Bridge between the orchestrator and pluggy plugins.

    Owns the two non-AI hook call paths:
    * ``apply_template_pool`` — pre-generate a pool of candidate values
      for columns the built-in mappers could not match deterministically
      (calls the ``sqlseed_pre_generate_templates`` hook).
    * ``apply_batch_transforms`` — let plugins transform a batch of
      rows post-generation (calls the ``sqlseed_transform_batch`` hook).

    The AI suggestion path (formerly ``apply_ai_suggestions``) was moved
    to ``sqlseed_ai.ai_mediator`` and is invoked by the orchestrator
    via the ``sqlseed_apply_ai_suggestions`` pluggy hook.
    """

    def __init__(
        self,
        plugins: PluginManager,
        db: DatabaseAdapter,
        schema: SchemaInferrer,
    ) -> None:
        self._plugins = plugins
        self._db = db
        self._schema = schema

    def _iter_template_eligible_specs(
        self,
        specs: dict[str, GeneratorSpec],
        column_infos: list[Any],
        configured: set[str],
        unique_columns: set[str] | None = None,
    ) -> Iterator[tuple[str, GeneratorSpec, Any]]:
        unique_cols = unique_columns or set()
        for col_name, spec in specs.items():
            if spec.generator_name != "string":
                continue
            if col_name in configured:
                continue
            if col_name in unique_cols:
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
        unique_columns: set[str] | None = None,
    ) -> dict[str, GeneratorSpec]:
        configured = user_configured_columns or set()
        needs_template = any(
            True for _ in self._iter_template_eligible_specs(specs, column_infos, configured, unique_columns)
        )
        if not needs_template:
            return specs
        # list() is required: loop body mutates `specs` via __setitem__,
        # and the generator yields from specs.items(). Without snapshotting
        # first, iterating would raise RuntimeError.
        eligible = list(self._iter_template_eligible_specs(specs, column_infos, configured, unique_columns))
        # Batch-fetch sample rows once for all eligible columns (avoids N+1 queries).
        sample_rows: list[dict[str, Any]] = []
        with contextlib.suppress(ValueError, OSError, RuntimeError, SAOperationalError):
            sample_rows = self._db.get_sample_rows(table_name, limit=10)

        for col_name, _, col_info in eligible:
            # Extract per-column values from the batch-fetched sample rows.
            sample_data_for_col: list[Any] = [row[col_name] for row in sample_rows if col_name in row]

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
