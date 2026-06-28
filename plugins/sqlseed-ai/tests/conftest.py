"""Pytest fixtures for sqlseed-ai tests.

Provides ``mediator_ctx`` (real RawSQLiteAdapter + SchemaInferrer on a
tiny ``t(id, name)`` schema) so AI mediator tests exercise the real
db/schema call path rather than mocks.

Shared fixtures (``tmp_db``, ``unique_test_db``, ``available_llm_backend``,
``pg_url``, etc.) are defined in the rootdir ``conftest.py`` at the
repository root and are auto-discovered by pytest for all test files. No
``pytest_plugins`` declaration is needed here — the rootdir conftest is
loaded for every test file via standard conftest discovery.

Helper functions (``make_column_info``, ``create_simple_db``) remain in
``tests/conftest.py`` and are imported below via ``importlib`` to avoid
pylint's import-self false positive (both this file and ``tests/conftest.py``
are named ``conftest.py``).
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from sqlseed.core.schema import SchemaInferrer
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter

# Use importlib.import_module to dynamically load tests.conftest, avoiding
# the static `from tests.conftest import create_simple_db` which pylint
# resolves as import-self (both this file and tests/conftest.py are named
# conftest.py, and pylint resolves them as the same module). The dynamic
# import sidesteps the static analyzer while still providing access to
# create_simple_db (a helper function, not a fixture — fixtures are shared
# via the rootdir conftest.py auto-discovery).
_root_conftest = importlib.import_module("tests.conftest")
create_simple_db = _root_conftest.create_simple_db


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
