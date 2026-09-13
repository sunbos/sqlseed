"""Bulk optimization must preserve PostgreSQL constraints and user triggers."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from sqlseed.config.models import GeneratorConfig
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

pytestmark = pytest.mark.integration


def test_pg_bulk_optimization_preserves_foreign_keys(pg_url: str) -> None:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(pg_url)
        adapter.execute("CREATE TABLE bulk_fk_parents(id INTEGER PRIMARY KEY)").close()
        adapter.execute("CREATE TABLE bulk_fk_children(id INTEGER REFERENCES bulk_fk_parents(id))").close()
        try:
            adapter.optimize_for_bulk_write(20000)
            rows = iter([{"id": 999}])
            with pytest.raises(IntegrityError, match="foreign key constraint"):
                adapter.batch_insert("bulk_fk_children", rows)
            assert adapter.get_row_count("bulk_fk_children") == 0
        finally:
            adapter.restore_settings()
            adapter.execute("DROP TABLE bulk_fk_children").close()
            adapter.execute("DROP TABLE bulk_fk_parents").close()


def test_pg_bulk_optimization_preserves_trigger_results(pg_url: str) -> None:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(pg_url)
        adapter.execute("CREATE TABLE bulk_trigger_items(value INTEGER)").close()
        adapter.execute(
            "CREATE FUNCTION bulk_trigger_filter() RETURNS trigger LANGUAGE plpgsql AS "
            "'BEGIN IF NEW.value % 2 = 1 THEN RETURN NULL; END IF; RETURN NEW; END'"
        ).close()
        adapter.execute(
            "CREATE TRIGGER bulk_trigger_filter BEFORE INSERT ON bulk_trigger_items "
            "FOR EACH ROW EXECUTE FUNCTION bulk_trigger_filter()"
        ).close()
        try:
            adapter.optimize_for_bulk_write(20000)
            inserted = adapter.batch_insert("bulk_trigger_items", iter({"value": i} for i in range(20000)))
            assert inserted == 10000
            assert adapter.get_row_count("bulk_trigger_items") == 10000
        finally:
            adapter.restore_settings()
            adapter.execute("DROP TABLE bulk_trigger_items").close()
            adapter.execute("DROP FUNCTION bulk_trigger_filter()").close()


@pytest.mark.parametrize("optimize", [False, True])
@pytest.mark.parametrize("reject", [False, True])
def test_pg_configured_fill_preserves_triggers_and_restores_settings(pg_url: str, optimize: bool, reject: bool) -> None:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(pg_url)
        adapter.execute("CREATE TABLE configured_bulk_items(value INTEGER)").close()
        action = "RAISE EXCEPTION 'bulk guard triggered';" if reject else "RETURN NULL;"
        adapter.execute(
            f"CREATE FUNCTION configured_bulk_guard() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN {action} END$$"
        ).close()
        adapter.execute(
            "CREATE TRIGGER configured_bulk_guard BEFORE INSERT ON configured_bulk_items "
            "FOR EACH ROW EXECUTE FUNCTION configured_bulk_guard()"
        ).close()
        try:
            config = GeneratorConfig(url=pg_url, provider="base", optimize_pragma=optimize)
            with DataOrchestrator.from_config(config) as orch:
                before = orch.query("SHOW synchronous_commit")
                result = orch.fill_table(
                    "configured_bulk_items",
                    count=10001,
                    columns={"value": {"generator": "choice", "params": {"choices": [1]}}},
                    seed=42,
                    skip_ai=True,
                )
                assert result.count == 0
                assert bool(result.errors) is reject
                if reject:
                    assert "bulk guard triggered" in result.errors[0]
                assert orch.query("SHOW synchronous_commit") == before
                assert orch.query("SHOW session_replication_role") == [{"session_replication_role": "origin"}]
            assert adapter.get_row_count("configured_bulk_items") == 0
        finally:
            adapter.execute("DROP TABLE configured_bulk_items").close()
            adapter.execute("DROP FUNCTION configured_bulk_guard()").close()
