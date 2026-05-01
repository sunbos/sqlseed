from __future__ import annotations

import collections
from typing import TYPE_CHECKING, Any

from sqlseed._utils.logger import get_logger
from sqlseed._utils.sql_safe import validate_table_name

if TYPE_CHECKING:
    from sqlseed.database._protocol import ColumnInfo, DatabaseAdapter, ForeignKeyInfo, IndexInfo

logger = get_logger(__name__)


class SchemaInferrer:
    def __init__(self, db_adapter: DatabaseAdapter) -> None:
        self._db = db_adapter

    def _validate(self, table_name: str) -> None:
        validate_table_name(table_name)

    def get_column_info(self, table_name: str) -> list[ColumnInfo]:
        self._validate(table_name)
        return list(self._db.get_column_info(table_name))

    def get_foreign_keys(self, table_name: str) -> list[ForeignKeyInfo]:
        self._validate(table_name)
        return list(self._db.get_foreign_keys(table_name))

    def get_table_names(self) -> list[str]:
        return list(self._db.get_table_names())

    def get_primary_keys(self, table_name: str) -> list[str]:
        self._validate(table_name)
        return list(self._db.get_primary_keys(table_name))

    def get_table_schema(self, table_name: str) -> dict[str, ColumnInfo]:
        columns = self.get_column_info(table_name)
        return {col.name: col for col in columns}

    def get_index_info(self, table_name: str) -> list[IndexInfo]:
        self._validate(table_name)
        return list(self._db.get_index_info(table_name))

    def detect_unique_columns(self, table_name: str) -> set[str]:
        unique_cols: set[str] = set()
        try:
            indexes = self.get_index_info(table_name)
            for idx in indexes:
                if idx.unique and len(idx.columns) == 1:
                    unique_cols.add(idx.columns[0])
        except (ValueError, OSError):
            logger.debug("Failed to detect unique constraints from indexes", table_name=table_name)

        try:
            pks = self._db.get_primary_keys(table_name)
            column_infos = self.get_column_info(table_name)
            autoincrement_pks = {c.name for c in column_infos if c.is_primary_key and c.is_autoincrement}
            for pk in pks:
                if pk not in autoincrement_pks:
                    unique_cols.add(pk)
        except (ValueError, OSError):
            logger.debug("Failed to detect PK unique constraints", table_name=table_name)

        return unique_cols

    def get_sample_data(self, table_name: str, limit: int = 5) -> list[dict[str, Any]]:
        self._validate(table_name)
        return self._db.get_sample_rows(table_name, limit=limit)

    def profile_column_distribution(
        self,
        table_name: str,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        self._validate(table_name)
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
                counter = collections.Counter(non_null_values)
                top5 = counter.most_common(5)
                profile["top_values"] = [
                    {"value": str(v)[:50], "frequency": round(c / len(non_null_values), 3)} for v, c in top5
                ]
            else:
                profile["top_values"] = []

            numeric_values = [v for v in non_null_values if isinstance(v, int | float)]
            if numeric_values:
                profile["value_range"] = {"min": min(numeric_values), "max": max(numeric_values)}
            else:
                profile["value_range"] = None

        except (ValueError, OSError):
            profile["error"] = "failed to profile"

        return profile
