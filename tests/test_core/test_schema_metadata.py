"""Optional metadata failures remain distinct from an empty schema."""

from __future__ import annotations

import pytest

from sqlseed.core.schema_metadata import SchemaMetadataError, SchemaMetadataReader
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter


def test_metadata_reader_uses_real_adapter_and_preserves_sql_identifiers(tmp_path) -> None:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(tmp_path / "metadata.db"))
        adapter.execute('CREATE TABLE "odd-table" (id INTEGER PRIMARY KEY, value INT CHECK(value > 0))')
        reader = SchemaMetadataReader(adapter)
        assert [column.name for column in reader.columns("odd-table")] == ["id", "value"]
        assert [check.expression for check in reader.checks("odd-table")] == ["value > 0"]
        assert 'CREATE TABLE "odd-table"' in reader.sqlite_ddl("odd-table")
        assert reader.sqlite_ddl("missing") == ""
        assert not list(reader.sqlite_index_predicates("odd-table"))


@pytest.mark.parametrize("operation", ["columns", "checks", "sqlite_ddl", "sqlite_index_predicates"])
def test_closed_adapter_reports_operation_and_preserves_cause(operation: str) -> None:
    reader = SchemaMetadataReader(SQLAlchemyAdapter())
    read = getattr(reader, operation)
    if operation in {"checks", "sqlite_index_predicates"}:
        result = read("records")
        with pytest.raises(SchemaMetadataError) as caught:
            list(result)
    else:
        with pytest.raises(SchemaMetadataError) as caught:
            read("records")
    assert caught.value.table_name == "records"
    assert caught.value.operation == operation
    assert isinstance(caught.value.__cause__, RuntimeError)
