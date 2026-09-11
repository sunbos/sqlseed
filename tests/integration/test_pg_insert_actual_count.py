"""Real PostgreSQL counts across insertmanyvalues pages and BEFORE triggers."""

from __future__ import annotations

import pytest

from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

pytestmark = pytest.mark.integration


def test_pg_execute_preserves_percent_sql_and_binds_values(pg_url: str) -> None:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(pg_url)
        cursor = adapter.execute("SELECT 5 % 2, '50% complete'")
        try:
            assert cursor.fetchone() == (1, "50% complete")
        finally:
            cursor.close()
        value = "x'); DROP TABLE items; -- 50%"
        cursor = adapter.execute("SELECT %s::text, %s::int", (value, 42))
        try:
            assert cursor.fetchone() == (value, 42)
        finally:
            cursor.close()


def test_pg_trigger_skips_are_counted_across_returning_pages(pg_url: str) -> None:
    adapter = SQLAlchemyAdapter()
    adapter.connect(pg_url)
    try:
        adapter.execute("CREATE TABLE actual_insert_counts(value INTEGER)").close()
        adapter.execute(
            "CREATE FUNCTION skip_odd_count_values() RETURNS trigger LANGUAGE plpgsql AS "
            "'BEGIN IF NEW.value % 2 = 1 THEN RETURN NULL; END IF; RETURN NEW; END'"
        ).close()
        adapter.execute(
            "CREATE TRIGGER skip_odd_count_values BEFORE INSERT ON actual_insert_counts "
            "FOR EACH ROW EXECUTE FUNCTION skip_odd_count_values()"
        ).close()
        inserted = adapter.batch_insert(
            "actual_insert_counts", iter({"value": i} for i in range(2501)), batch_size=2501
        )
        assert inserted == 1251
        assert adapter.get_row_count("actual_insert_counts") == 1251
    finally:
        try:
            adapter.execute("DROP TABLE IF EXISTS actual_insert_counts").close()
            adapter.execute("DROP FUNCTION IF EXISTS skip_odd_count_values()").close()
        finally:
            adapter.close()
