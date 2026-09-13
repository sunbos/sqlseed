"""Shared pytest fixtures for sqlseed-cli tests.

Shared fixtures (``tmp_db``, ``tmp_db_with_data``, ``unique_test_db``,
etc.) are defined in the rootdir ``conftest.py`` at the repository root
and are auto-discovered by pytest for all test files. No
``pytest_plugins`` declaration is needed here — the rootdir conftest is
loaded for every test file via standard conftest discovery.

The root ``tmp_db`` fixture creates a ``users`` table with the ``name``
column (not ``username``) plus an ``orders`` table with a foreign key,
matching the schema expected by the CLI tests.
"""

from __future__ import annotations
