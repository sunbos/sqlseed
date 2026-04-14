from __future__ import annotations

from typing import Any

from sqlseed.config.models import ColumnConfig
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.plugins.hookspecs import hookimpl


class TestDataOrchestrator:
    def test_fill_basic(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            result = orch.fill_table("users", count=100)
            assert result.count == 100
            assert result.elapsed > 0

    def test_fill_with_seed(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            result1 = orch.preview_table("users", count=5, seed=42)
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            result2 = orch.preview_table("users", count=5, seed=42)
        assert result1 == result2

    def test_fill_with_clear(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch.fill_table("users", count=50)
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            result = orch.fill_table("users", count=30, clear_before=True)
            assert result.count == 30

    def test_fill_with_columns(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            result = orch.fill_table(
                "users",
                count=10,
                columns={
                    "name": "name",
                    "email": "email",
                    "age": {"type": "integer", "min_value": 18, "max_value": 65},
                },
            )
            assert result.count == 10

    def test_preview(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            rows = orch.preview_table("users", count=3)
            assert len(rows) == 3
            assert "name" in rows[0]

    def test_report(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            report = orch.report()
            assert "users" in report

    def test_fill_with_foreign_key(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch.fill_table("users", count=10)
            result = orch.fill_table("orders", count=50)
            assert result.count == 50

    def test_report_not_connected(self) -> None:
        orch = DataOrchestrator("/tmp/nonexistent.db", provider_name="base")
        report = orch.report()
        assert "Not connected" in report

    def test_fill_with_column_configs(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            col_configs = [
                ColumnConfig(name="name", generator="name"),
                ColumnConfig(name="email", generator="email"),
            ]
            result = orch.fill_table("users", count=5, column_configs=col_configs)
            assert result.count == 5

    def test_fill_with_foreign_key_config(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch.fill_table("users", count=10)
            result = orch.fill_table(
                "orders",
                count=20,
                columns={
                    "user_id": {
                        "type": "foreign_key",
                        "ref_table": "users",
                        "ref_column": "id",
                        "strategy": "random",
                    },
                },
            )
            assert result.count == 20

    def test_fill_nonexistent_table(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            result = orch.fill_table("nonexistent_table", count=10)
            assert len(result.errors) > 0

    def test_fill_with_mimesis_provider(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="mimesis") as orch:
            result = orch.fill_table("users", count=10)
            assert result.count == 10

    def test_fill_with_faker_provider(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="faker") as orch:
            result = orch.fill_table("users", count=10)
            assert result.count == 10

    def test_fill_no_optimize_pragma(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base", optimize_pragma=False) as orch:
            result = orch.fill_table("users", count=10)
            assert result.count == 10

    def test_fill_with_transform_batch_plugin(self, tmp_db) -> None:
        transform_log: list[str] = []

        class UpperCasePlugin:
            @hookimpl
            def sqlseed_transform_batch(self, table_name: str, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
                transform_log.append(table_name)
                for row in batch:
                    if "name" in row and isinstance(row["name"], str):
                        row["name"] = row["name"].upper()
                return batch

        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch._ensure_connected()
            orch._plugins._pm.register(UpperCasePlugin())
            result = orch.fill_table("users", count=5)
            assert result.count == 5
            assert "users" in transform_log

    def test_preview_with_transform_batch_plugin(self, tmp_db) -> None:
        class TagPlugin:
            @hookimpl
            def sqlseed_transform_batch(self, table_name: str, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
                for row in batch:
                    row["_source"] = "plugin"
                return batch

        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch._ensure_connected()
            orch._plugins._pm.register(TagPlugin())
            rows = orch.preview_table("users", count=3)
            assert len(rows) == 3
            assert all("_source" in r for r in rows)

    def test_preview_with_column_configs(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            col_configs = [
                ColumnConfig(name="name", generator="name"),
                ColumnConfig(name="email", generator="email"),
            ]
            rows = orch.preview_table("users", count=5, column_configs=col_configs)
            assert len(rows) == 5
            assert "name" in rows[0]

    def test_get_schema_context(self, tmp_db) -> None:
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            ctx = orch.get_schema_context("users")
            assert ctx["table_name"] == "users"
            assert len(ctx["columns"]) > 0
            assert isinstance(ctx["foreign_keys"], list)
            assert isinstance(ctx["indexes"], list)
            assert isinstance(ctx["sample_data"], list)
            assert "users" in ctx["all_table_names"]
            assert isinstance(ctx["distribution"], list)

    def test_fill_with_template_pool_plugin(self, tmp_db) -> None:
        class TemplatePlugin:
            @hookimpl
            def sqlseed_pre_generate_templates(
                self,
                table_name: str,
                column_name: str,
                column_type: str,
                count: int,
                sample_data: list[Any],
            ) -> list[Any] | None:
                if column_name == "bio":
                    return ["template_bio_1", "template_bio_2", "template_bio_3"]
                return None

        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch._ensure_connected()
            orch._plugins._pm.register(TemplatePlugin())
            result = orch.fill_table("users", count=5)
            assert result.count == 5
