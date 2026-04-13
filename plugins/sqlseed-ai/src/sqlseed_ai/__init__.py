from __future__ import annotations

from typing import Any

from sqlseed.plugins.hookspecs import hookimpl
from sqlseed_ai.analyzer import SchemaAnalyzer
from sqlseed_ai.config import AIConfig


class AISqlseedPlugin:
    def __init__(self) -> None:
        self._analyzer: SchemaAnalyzer | None = None

    def _get_analyzer(self) -> SchemaAnalyzer:
        if self._analyzer is None:
            self._analyzer = SchemaAnalyzer()
        return self._analyzer

    @hookimpl
    def sqlseed_ai_analyze_table(
        self,
        table_name: str,
        columns: list[Any],
        indexes: list[dict[str, Any]],
        sample_data: list[dict[str, Any]],
        foreign_keys: list[Any],
        all_table_names: list[str],
    ) -> dict[str, Any] | None:
        analyzer = self._get_analyzer()
        return analyzer.analyze_table(
            table_name=table_name,
            columns=columns,
            indexes=indexes,
            sample_data=sample_data,
            foreign_keys=foreign_keys,
            all_table_names=all_table_names,
        )

    @hookimpl
    def sqlseed_register_providers(self, registry: Any) -> None:
        pass

    @hookimpl
    def sqlseed_register_column_mappers(self, mapper: Any) -> None:
        pass


plugin = AISqlseedPlugin()
