"""Plain PostgreSQL URLs use the psycopg3 driver supplied by the postgres extra."""

from __future__ import annotations

from contextlib import closing

import pytest
from click.testing import CliRunner
from sqlalchemy.engine import make_url
from sqlseed_cli.main import cli

import sqlseed
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("driver", ["postgresql", "postgresql+psycopg"])
def test_pg_plain_and_explicit_driver_urls_preserve_target_and_generate(pg_url: str, driver: str) -> None:
    parsed = make_url(pg_url).set(drivername=driver).update_query_dict({"application_name": "sqlseed URL @:/ audit"})
    target = parsed.render_as_string(hide_password=False)
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(target)
        assert adapter._db_path == target
        assert adapter._db_url == target
        assert adapter._engine is not None
        assert adapter._engine.url == parsed.set(drivername="postgresql+psycopg")
        with closing(adapter.execute("SELECT current_setting('application_name')")) as cursor:
            assert cursor.fetchone() == ("sqlseed URL @:/ audit",)
        adapter.execute("CREATE TABLE driver_url_audit(id SERIAL PRIMARY KEY, name TEXT NOT NULL)").close()
        try:
            samples = sqlseed.preview(url=target, table="driver_url_audit", count=3, provider="base")
            assert len(samples) == 3
            assert adapter.get_row_count("driver_url_audit") == 0
            result = sqlseed.fill(url=target, table="driver_url_audit", count=3, provider="base", skip_ai=True)
            assert result.count == 3
            assert not result.errors
            invocation = CliRunner().invoke(
                cli, ["fill", "--url", target, "-t", "driver_url_audit", "-n", "2", "--provider", "base"]
            )
            assert invocation.exit_code == 0, invocation.output
            assert adapter.get_row_count("driver_url_audit") == 5
        finally:
            adapter.execute("DROP TABLE driver_url_audit").close()
