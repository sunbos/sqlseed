from __future__ import annotations

from typing import Any


class SchemaAnalyzer:

    def analyze(self, db_path: str, table_name: str | None = None) -> dict[str, Any]:
        return {}

    def suggest_config(self, db_path: str) -> dict[str, Any]:
        return {}
