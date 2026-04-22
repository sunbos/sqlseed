from __future__ import annotations

from sqlseed.plugins.manager import PluginManager


class TestPluginManager:
    def test_create_plugin_manager(self) -> None:
        pm = PluginManager()
        assert isinstance(pm, PluginManager)

    def test_register_plugin(self) -> None:
        pm = PluginManager()

        class MyPlugin:
            @staticmethod
            def sqlseed_before_generate(table_name, count, config):
                pass  # Dummy hook method for testing  # Dummy hook method for testing

        plugin = MyPlugin()
        pm.register(plugin, name="my_plugin")
        assert pm.is_registered(plugin)

    def test_get_plugins(self) -> None:
        pm = PluginManager()
        plugins = pm.get_plugins()
        assert isinstance(plugins, set)

    def test_hook_attribute(self) -> None:
        pm = PluginManager()
        assert hasattr(pm, "hook")

    def test_load_plugins(self) -> None:
        pm = PluginManager()
        pm.load_plugins()

    def test_unregister_plugin(self) -> None:
        pm = PluginManager()

        class MyPlugin:
            @staticmethod
            def sqlseed_before_generate(table_name, count, config):
                pass  # Dummy hook method for testing

        plugin = MyPlugin()
        pm.register(plugin, name="my_plugin")
        assert pm.is_registered(plugin)
        pm.unregister(plugin)
        assert not pm.is_registered(plugin)
