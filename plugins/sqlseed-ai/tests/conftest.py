"""Pytest fixtures for sqlseed-ai tests.

Provides ``mediator_ctx`` (real RawSQLiteAdapter + SchemaInferrer on a
tiny ``t(id, name)`` schema) so AI mediator tests exercise the real
db/schema call path rather than mocks.

Also re-exports integration fixtures (``unique_test_db``,
``available_llm_backend``, ``pg_url``) and the ``make_column_info`` helper
from the root ``tests/conftest.py`` so that tests moved from the root
test directory (Phase F) can use the same fixtures without duplication.
"""

from __future__ import annotations

from typing import Any

import pytest

from sqlseed.core.schema import SchemaInferrer
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter
from tests.conftest import (  # noqa: F401  (re-exported for pytest fixture discovery)
    available_llm_backend,
    create_simple_db,
    create_tmp_db,
    create_tmp_db_full,
    create_unique_test_db,
    make_column_info,
    pg_url,
)


class MediatorContext:
    def __init__(self, adapter: RawSQLiteAdapter, schema: SchemaInferrer) -> None:
        self.adapter = adapter
        self.schema = schema


@pytest.fixture
def mediator_ctx(tmp_path: Any):
    db_path = str(tmp_path / "test.db")
    create_simple_db(db_path)

    adapter = RawSQLiteAdapter()
    adapter.connect(db_path)
    schema = SchemaInferrer(adapter)
    ctx = MediatorContext(adapter, schema)
    yield ctx
    adapter.close()
