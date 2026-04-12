from __future__ import annotations

from typing import Any

from sqlseed.plugins.hookspecs import hookimpl


class AISqlseedPlugin:

    @hookimpl
    def sqlseed_ai_suggest_generator(
        self,
        column_name: str,
        column_type: str,
        table_name: str,
        all_column_names: list[str],
    ) -> dict[str, Any] | None:
        return None

    @hookimpl
    def sqlseed_register_providers(self, registry: Any) -> None:
        pass

    @hookimpl
    def sqlseed_register_column_mappers(self, mapper: Any) -> None:
        pass
