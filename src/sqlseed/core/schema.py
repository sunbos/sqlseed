from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlseed.database._protocol import ColumnInfo, ForeignKeyInfo, IndexInfo


class SchemaInferrer:
    def __init__(self, db_adapter: Any) -> None:
        self._db = db_adapter

    def get_column_info(self, table_name: str) -> list[ColumnInfo]:
        return list(self._db.get_column_info(table_name))

    def get_foreign_keys(self, table_name: str) -> list[ForeignKeyInfo]:
        return list(self._db.get_foreign_keys(table_name))

    def get_table_names(self) -> list[str]:
        return list(self._db.get_table_names())

    def get_primary_keys(self, table_name: str) -> list[str]:
        return list(self._db.get_primary_keys(table_name))

    def get_table_schema(self, table_name: str) -> dict[str, ColumnInfo]:
        columns = self.get_column_info(table_name)
        return {col.name: col for col in columns}

    def get_index_info(self, table_name: str) -> list[IndexInfo]:
        return list(self._db.get_index_info(table_name))

    def get_sample_data(self, table_name: str, limit: int = 5) -> list[dict[str, Any]]:
        return self._db.get_sample_rows(table_name, limit=limit)

    def profile_column_distribution(
        self,
        table_name: str,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        columns = self.get_column_info(table_name)
        row_count = self._db.get_row_count(table_name)

        if row_count == 0:
            return []

        profiles: list[dict[str, Any]] = []
        for col in columns:
            if col.is_primary_key and col.is_autoincrement:
                continue

            profile = self._profile_single_column(table_name, col.name, row_count, limit)
            profiles.append(profile)

        return profiles

    def _profile_single_column(
        self,
        table_name: str,
        column_name: str,
        total_rows: int,
        limit: int,
    ) -> dict[str, Any]:
        profile: dict[str, Any] = {"column": column_name}

        try:
            values = self._db.get_column_values(table_name, column_name, limit=limit)

            null_count = sum(1 for v in values if v is None)
            non_null_values = [v for v in values if v is not None]

            profile["null_ratio"] = round(null_count / len(values), 3) if values else 0.0
            profile["distinct_count"] = len(set(non_null_values))
            profile["sample_size"] = len(values)
            profile["total_rows"] = total_rows

            if non_null_values:
                from collections import Counter

                counter = Counter(non_null_values)
                top5 = counter.most_common(5)
                profile["top_values"] = [
                    {"value": str(v)[:50], "frequency": round(c / len(non_null_values), 3)}
                    for v, c in top5
                ]
            else:
                profile["top_values"] = []

            numeric_values = [v for v in non_null_values if isinstance(v, (int, float))]
            if numeric_values:
                profile["value_range"] = {"min": min(numeric_values), "max": max(numeric_values)}
            else:
                profile["value_range"] = None

        except Exception:
            profile["error"] = "failed to profile"

        return profile
