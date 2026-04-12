from __future__ import annotations

import pluggy

from sqlseed.plugins.hookspecs import PROJECT_NAME, SqlseedHookSpec, hookimpl


class TestHookSpecs:
    def test_project_name(self) -> None:
        assert PROJECT_NAME == "sqlseed"

    def test_hookspec_has_register_providers(self) -> None:
        assert hasattr(SqlseedHookSpec, "sqlseed_register_providers")

    def test_hookspec_has_register_column_mappers(self) -> None:
        assert hasattr(SqlseedHookSpec, "sqlseed_register_column_mappers")

    def test_hookspec_has_ai_analyze_table(self) -> None:
        assert hasattr(SqlseedHookSpec, "sqlseed_ai_analyze_table")

    def test_hookspec_has_before_generate(self) -> None:
        assert hasattr(SqlseedHookSpec, "sqlseed_before_generate")

    def test_hookspec_has_after_generate(self) -> None:
        assert hasattr(SqlseedHookSpec, "sqlseed_after_generate")

    def test_hookspec_has_transform_row(self) -> None:
        assert hasattr(SqlseedHookSpec, "sqlseed_transform_row")

    def test_hookspec_has_transform_batch(self) -> None:
        assert hasattr(SqlseedHookSpec, "sqlseed_transform_batch")

    def test_hookspec_has_before_insert(self) -> None:
        assert hasattr(SqlseedHookSpec, "sqlseed_before_insert")

    def test_hookspec_has_after_insert(self) -> None:
        assert hasattr(SqlseedHookSpec, "sqlseed_after_insert")

    def test_hookimpl_marker(self) -> None:
        @hookimpl
        def sqlseed_before_generate(self, table_name: str, count: int, config: object) -> None:
            pass

        assert hasattr(sqlseed_before_generate, "sqlseed_impl")

    def test_plugin_manager_with_hookspec(self) -> None:
        pm = pluggy.PluginManager(PROJECT_NAME)
        pm.add_hookspecs(SqlseedHookSpec)
        assert hasattr(pm.hook, "sqlseed_before_generate")
        assert hasattr(pm.hook, "sqlseed_after_generate")
        assert hasattr(pm.hook, "sqlseed_transform_batch")

    def test_ai_analyze_table_firstresult(self) -> None:
        pm = pluggy.PluginManager(PROJECT_NAME)
        pm.add_hookspecs(SqlseedHookSpec)
        spec = pm.hook.sqlseed_ai_analyze_table
        assert spec.spec is not None

    def test_register_and_call_hook(self) -> None:
        pm = pluggy.PluginManager(PROJECT_NAME)
        pm.add_hookspecs(SqlseedHookSpec)

        call_log: list[str] = []

        class TestPlugin:
            @hookimpl
            def sqlseed_before_generate(self, table_name: str, count: int, config: object) -> None:
                call_log.append(f"before:{table_name}:{count}")

        pm.register(TestPlugin())
        pm.hook.sqlseed_before_generate(table_name="users", count=100, config=None)
        assert call_log == ["before:users:100"]
