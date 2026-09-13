"""Keep metadata tokens and session settings within their existing ASCII grammar."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sqlseed._utils.sql_safe import quote_identifier
from sqlseed.database._bulk_optimizer import PostgresBulkOptimizer
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("adapter_type", [SQLAlchemyAdapter, RawSQLiteAdapter])
@pytest.mark.parametrize(
    "column_name,expected_tokens",
    [
        ("amount_1", ("amount_1",)),
        ("_amount", ("_amount",)),
        ("price_é", ("price_",)),
        ("café", ("caf",)),
        ("x\uff11\uff12", ("x",)),
        ("价格", ()),
    ],
)
def test_check_metadata_keeps_ascii_token_boundaries(
    tmp_path: Path,
    adapter_type: type[SQLAlchemyAdapter] | type[RawSQLiteAdapter],
    column_name: str,
    expected_tokens: tuple[str, ...],
) -> None:
    path = tmp_path / "tokens.db"
    identifier = quote_identifier(column_name)
    with sqlite_connection(path) as db:
        db.execute(f"CREATE TABLE amounts ({identifier} INTEGER CHECK ({identifier} >= 0))")
        db.execute("INSERT INTO amounts VALUES (1)")
    with adapter_type() as adapter:
        adapter.connect(str(path))
        checks = adapter.get_check_constraints("amounts")
        assert len(checks) == 1
        assert checks[0].columns == expected_tokens
        assert checks[0].expression == f"{identifier} >= 0"


@pytest.mark.parametrize("setting", ["synchronous_commit", "session_replication_role"])
@pytest.mark.parametrize(
    "value,accepted",
    [
        ("on", True),
        ("local_1", True),
        ("on\n", True),
        ("", False),
        ("オン", False),
        ("originé", False),
        ("\uff11\uff12", False),
        ("on'; RESET ALL; --", False),
    ],
)
def test_restore_settings_keeps_ascii_validation_boundary(setting: str, value: str, accepted: bool) -> None:
    statements: list[str] = []
    optimizer = PostgresBulkOptimizer(statements.append)
    if setting == "synchronous_commit":
        optimizer._original_synchronous_commit = value
    else:
        optimizer._original_replication_role = value

    optimizer.restore()

    expected = [f"SET {setting} = '{value}'"] if accepted else []
    assert statements == expected
