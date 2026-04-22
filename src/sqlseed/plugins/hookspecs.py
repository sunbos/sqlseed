from __future__ import annotations

from typing import Any

import pluggy

hookspec = pluggy.HookspecMarker("sqlseed")
hookimpl = pluggy.HookimplMarker("sqlseed")

PROJECT_NAME = "sqlseed"


class SqlseedHookSpec:
    @hookspec
    def sqlseed_register_providers(self, registry: Any) -> None:
        raise NotImplementedError

    @hookspec
    def sqlseed_register_column_mappers(self, mapper: Any) -> None:
        raise NotImplementedError

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
        """
        [AI Hook] 分析整张表，返回完整的列配置建议。
        """

    @hookspec
    def sqlseed_before_generate(
        self,
        table_name: str,
        count: int,
        config: Any,
    ) -> None:
        raise NotImplementedError

    @hookspec
    def sqlseed_after_generate(
        self,
        table_name: str,
        count: int,
        elapsed: float,
    ) -> None:
        raise NotImplementedError

    @hookspec
    def sqlseed_transform_row(
        self,
        table_name: str,
        row: dict[str, Any],
    ) -> dict[str, Any] | None:
        """
        Transform/modify each generated row.
        Return modified row, or None to keep unchanged.
        Note: This hook is in the hot path - performance sensitive.
        """

    @hookspec
    def sqlseed_transform_batch(
        self,
        table_name: str,
        batch: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        """
        Transform/modify a batch of generated data.
        Multiple plugins can chain: each plugin's output feeds into the next.
        """

    @hookspec
    def sqlseed_before_insert(
        self,
        table_name: str,
        batch_number: int,
        batch_size: int,
    ) -> None:
        raise NotImplementedError

    @hookspec
    def sqlseed_after_insert(
        self,
        table_name: str,
        batch_number: int,
        rows_inserted: int,
    ) -> None:
        raise NotImplementedError

    @hookspec
    def sqlseed_shared_pool_loaded(
        self,
        table_name: str,
        shared_pool: Any,
    ) -> None:
        """
        Called after a table's generated values are loaded into the shared pool.
        Other plugins can use this to track cross-table associations.
        """

    @hookspec(firstresult=True)
    def sqlseed_pre_generate_templates(
        self,
        table_name: str,
        column_name: str,
        column_type: str,
        count: int,
        sample_data: list[Any],
    ) -> list[Any] | None:
        """
        [AI Hook] Pre-generate candidate value pool for columns that cannot match
        a deterministic generator. Called before DataStream creation.
        Returns a list of template values, or None if the plugin does not handle this column.
        """
