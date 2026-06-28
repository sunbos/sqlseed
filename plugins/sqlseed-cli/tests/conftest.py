"""Shared pytest fixtures for sqlseed-cli tests.

Re-exports core fixtures (``tmp_db``, ``tmp_db_with_data``,
``unique_test_db``) from the root ``tests/conftest.py`` so that CLI tests
moved from the root test directory (Phase F) can use the same database
fixtures without duplicating schema definitions.

The root ``tmp_db`` fixture creates a ``users`` table with the ``name``
column (not ``username``) plus an ``orders`` table with a foreign key,
matching the schema expected by the CLI tests.
"""

from __future__ import annotations

from tests.conftest import (  # noqa: F401  (re-exported for pytest fixture discovery)
    create_tmp_db,
    create_tmp_db_full,
    create_tmp_db_with_data,
    create_unique_test_db,
)
