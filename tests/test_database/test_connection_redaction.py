"""Real connection diagnostics must not reveal URL credentials."""

from __future__ import annotations

import subprocess
import sys
import traceback
from typing import TYPE_CHECKING

import pytest

from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "password", ["synthetic-userinfo", "synthetic?value", "synthetic/value", "synthetic#value", "synthetic value"]
)
def test_invalid_url_redacts_exception_and_chained_diagnostic(password: str) -> None:
    target = f"sqlite://audit-user:{password}@host/db?password=synthetic-query&timeout=3"
    with SQLAlchemyAdapter() as adapter, pytest.raises(ValueError, match="Invalid database URL") as captured:
        adapter.connect(target)
    rendered = "".join(traceback.format_exception(captured.value))
    assert password not in rendered
    assert "synthetic-query" not in rendered
    assert "host/db?password=***&timeout=3" in str(captured.value)


@pytest.mark.parametrize("separator", [" ", "\t", "#", "'", '"', ")"])
def test_invalid_url_query_password_is_fully_redacted(separator: str) -> None:
    target = f"sqlite://host/db?password=first-secret{separator}second-secret&timeout=3"
    with SQLAlchemyAdapter() as adapter, pytest.raises(ValueError, match="Invalid database URL") as captured:
        adapter.connect(target)
    rendered = "".join(traceback.format_exception(captured.value))
    assert "first-secret" not in rendered
    assert "second-secret" not in rendered
    assert "host/db?password=***&timeout=3" in str(captured.value)


def test_successful_connection_redacts_debug_logs_without_changing_target(tmp_path: Path) -> None:
    script = """
import sys
from sqlseed._utils.logger import configure_logging
configure_logging('DEBUG')
from sqlseed.core.orchestrator import DataOrchestrator
target='sqlite:///'+sys.argv[1]+'?password=synthetic-query&timeout=3'
with DataOrchestrator(target, provider_name='base', optimize_pragma=False) as orch:
    assert orch.database_adapter._db_path == target
    assert orch.query('SELECT 7 AS value') == [{'value':7}]
print('connection preserved')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "redacted.db")],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert result.stdout.strip() == "connection preserved"
    assert "synthetic-query" not in result.stderr
    assert "Connected to database" in result.stderr
    assert "Closed SQLAlchemy connection" in result.stderr
    assert "Using SQLAlchemyAdapter" in result.stderr
