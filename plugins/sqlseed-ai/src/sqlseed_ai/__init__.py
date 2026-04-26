from __future__ import annotations

import re
from typing import Any

from sqlseed_ai.analyzer import SchemaAnalyzer
from sqlseed_ai.config import AIConfig

from sqlseed.plugins.hookspecs import hookimpl

_SIMPLE_COL_RE = re.compile(
    r"(^|[_\s])("
    r"name|email|phone|address|url|uuid|"
    r"date|time|datetime|timestamp|boolean|"
    r"int|float|double|real|text|string|"
    r"char|varchar|blob|byte|id|code|title|"
    r"description|status|type|category|count|"
    r"amount|price|value|number|index|order|level"
    r")($|[_\s])",
    re.IGNORECASE,
)


class AISqlseedPlugin:
    def __init__(self) -> None:
        self._analyzer: SchemaAnalyzer | None = None

    def _get_analyzer(self) -> SchemaAnalyzer:
        if self._analyzer is None:
            config = AIConfig.from_env()
            config.resolve_model()
            self._analyzer = SchemaAnalyzer(config=config)
        return self._analyzer

    def _is_simple_column(self, column_name: str, column_type: str) -> bool:
        return bool(_SIMPLE_COL_RE.search(column_name) or _SIMPLE_COL_RE.search(column_type))

    @hookimpl
    def sqlseed_ai_analyze_table(self, **kwargs: Any) -> dict[str, Any] | None:
        analyzer = self._get_analyzer()
        return analyzer.analyze_table_from_ctx(**kwargs)

    @hookimpl
    def sqlseed_pre_generate_templates(
        self,
        table_name: str,
        column_name: str,
        column_type: str,
        count: int,
        sample_data: list[Any],
    ) -> list[Any] | None:
        if self._is_simple_column(column_name, column_type):
            return None

        analyzer = self._get_analyzer()
        try:
            return analyzer.generate_template_values(
                column_name=column_name,
                column_type=column_type,
                count=min(count, 50),
                sample_data=sample_data,
                table_name=table_name,
            )
        except (ValueError, RuntimeError, OSError):
            return None

    @hookimpl
    def sqlseed_register_providers(self, registry: Any) -> None:
        _ = registry

    @hookimpl
    def sqlseed_register_column_mappers(self, mapper: Any) -> None:
        _ = mapper


plugin = AISqlseedPlugin()
