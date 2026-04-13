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
