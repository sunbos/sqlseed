"""pluggy plugin hook specification definitions.

12 hooks covering the full lifecycle of registration/generation/transformation/insertion.
"""

from __future__ import annotations

from typing import Any

import pluggy

# pluggy hookspec methods use placeholder parameters; they only define the
# hook signature for plugin implementers' reference. The `del` statements in
# each method body reference the parameters to suppress unused-argument
# warnings without changing the hook contract.

hookspec = pluggy.HookspecMarker("sqlseed")
hookimpl = pluggy.HookimplMarker("sqlseed")

PROJECT_NAME = "sqlseed"


class SqlseedHookSpec:
    """sqlseed plugin hook specification class.

    Defines 12 hooks for plugin implementers to override, covering the full
    data generation lifecycle: registration, before/after generation, row/batch
    transformation, before/after insertion, shared pool loading, and AI
    analysis. The ``sqlseed_apply_ai_suggestions`` hook is the high-level
    entry point used by the orchestrator; the lower-level
    ``sqlseed_ai_analyze_table`` hook is the LLM call itself and is invoked
    by the AI plugin's implementation of ``sqlseed_apply_ai_suggestions``.
    """

    @hookspec
    def sqlseed_register_providers(self, registry: Any) -> None:
        """Register data providers into the registry."""
        del registry

    @hookspec
    def sqlseed_register_column_mappers(self, mapper: Any) -> None:
        """Register column mapping rules into the mapper."""
        del mapper

    @hookspec(firstresult=True)
    def sqlseed_ai_analyze_table(
        self,
        table_name: str,
        columns: list[Any],
        indexes: list[dict[str, Any]],
        sample_data: list[dict[str, Any]],
        foreign_keys: list[Any],
        all_table_names: list[str],
    ) -> dict[str, Any] | None:
        """[AI Hook] Analyze an entire table and return complete column configuration suggestions."""
        del table_name, columns, indexes, sample_data, foreign_keys, all_table_names
        raise NotImplementedError

    @hookspec(firstresult=True)
    def sqlseed_apply_ai_suggestions(
        self,
        table_name: str,
        column_infos: list[Any],
        specs: dict[str, Any],
        user_configured_columns: set[str],
        db: Any,
        schema: Any,
    ) -> dict[str, Any] | None:
        """[AI Hook] Apply AI-driven suggestions to column specs.

        This is the high-level entry point invoked by the orchestrator. The
        AI plugin implementation is responsible for: deciding whether AI is
        needed (e.g., unmatched ``string`` columns), building the analysis
        context from ``db``/``schema``, calling the lower-level
        ``sqlseed_ai_analyze_table`` hook, and merging the AI result back
        into ``specs``. Returns the updated ``specs`` dict, or ``None`` if
        no AI plugin handles this call (in which case the orchestrator
        keeps the original ``specs`` unchanged).
        """
        del table_name, column_infos, specs, user_configured_columns, db, schema
        raise NotImplementedError

    @hookspec
    def sqlseed_before_generate(
        self,
        table_name: str,
        count: int,
        config: Any,
    ) -> None:
        """Callback before data generation."""
        del table_name, count, config

    @hookspec
    def sqlseed_after_generate(
        self,
        table_name: str,
        count: int,
        elapsed: float,
    ) -> None:
        """Callback after data generation."""
        del table_name, count, elapsed

    @hookspec
    def sqlseed_transform_row(
        self,
        table_name: str,
        row: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Transform a single row of data. Returns the modified row, or None to indicate no modification.

        Note: This hook is on the hot path and is performance-sensitive.
        """
        del table_name, row
        raise NotImplementedError

    @hookspec
    def sqlseed_transform_batch(
        self,
        table_name: str,
        batch: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        """Transform a batch of data.

        Supports chained application: each plugin's output becomes the next plugin's input.
        """
        del table_name, batch
        raise NotImplementedError

    @hookspec
    def sqlseed_before_insert(
        self,
        table_name: str,
        batch_number: int,
        batch_size: int,
    ) -> None:
        """Callback before batch insertion."""
        del table_name, batch_number, batch_size

    @hookspec
    def sqlseed_after_insert(
        self,
        table_name: str,
        batch_number: int,
        rows_inserted: int,
    ) -> None:
        """Callback after batch insertion."""
        del table_name, batch_number, rows_inserted

    @hookspec
    def sqlseed_shared_pool_loaded(
        self,
        table_name: str,
        shared_pool: Any,
    ) -> None:
        """Called after a table's generated values are loaded into the shared pool.

        Other plugins can use this to track cross-table associations.
        """
        del table_name, shared_pool

    @hookspec(firstresult=True)
    def sqlseed_pre_generate_templates(
        self,
        table_name: str,
        column_name: str,
        column_type: str,
        count: int,
        sample_data: list[Any],
    ) -> list[Any] | None:
        """[AI Hook] Pre-generate a pool of candidate values for columns that cannot match a deterministic generator.

        Called before DataStream creation. Returns a list of template values, or None
        to indicate the plugin does not handle this column.
        """
        del table_name, column_name, column_type, count, sample_data
        raise NotImplementedError
