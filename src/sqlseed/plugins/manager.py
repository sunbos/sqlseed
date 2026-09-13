"""Plugin manager: wraps pluggy.PluginManager, supporting auto-discovery and registration."""

from __future__ import annotations

from typing import Any

import pluggy

from sqlseed._utils.logger import get_logger
from sqlseed.plugins.hookspecs import PROJECT_NAME, SqlseedHookSpec

logger = get_logger(__name__)


class PluginManager:
    """Plugin manager: wraps pluggy.PluginManager.

    Provides plugin loading, registration, unregistration, and querying.
    Auto-discovers installed sqlseed plugins via entry_points.
    """

    def __init__(self) -> None:
        """Initialize the plugin manager and register hook specifications."""
        self._pm = pluggy.PluginManager(PROJECT_NAME)
        self._pm.add_hookspecs(SqlseedHookSpec)

    def load_plugins(self) -> None:
        """Auto-load installed plugins from setuptools entry_points."""
        self._pm.load_setuptools_entrypoints(PROJECT_NAME)
        logger.debug("Loaded plugins", plugins=self._pm.get_plugins())

    def register(self, plugin: Any, name: str | None = None) -> None:
        """Register a plugin instance.

        Args:
            plugin: Plugin instance
            name: Optional plugin name; when None, uses the plugin's class name
        """
        self._pm.register(plugin, name=name)
        logger.debug("Registered plugin", name=name or str(plugin))

    def unregister(self, plugin: Any) -> None:
        """Unregister a previously registered plugin."""
        self._pm.unregister(plugin)

    @property
    def hook(self) -> Any:
        """Return the pluggy hook invocation entry point, used to trigger hook execution."""
        return self._pm.hook

    def get_plugins(self) -> set[Any]:
        """Return the set of all registered plugins."""
        return self._pm.get_plugins()

    def is_registered(self, plugin: Any) -> bool:
        """Check whether a plugin is registered."""
        return self._pm.is_registered(plugin)
