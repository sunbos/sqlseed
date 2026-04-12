from __future__ import annotations

from typing import Any

import pluggy

from sqlseed._utils.logger import get_logger
from sqlseed.plugins.hookspecs import PROJECT_NAME, SqlseedHookSpec

logger = get_logger(__name__)


class PluginManager:
    def __init__(self) -> None:
        self._pm = pluggy.PluginManager(PROJECT_NAME)
        self._pm.add_hookspecs(SqlseedHookSpec)

    def load_plugins(self) -> None:
        self._pm.load_setuptools_entrypoints(PROJECT_NAME)
        logger.debug("Loaded plugins", plugins=self._pm.get_plugins())

    def register(self, plugin: Any, name: str | None = None) -> None:
        self._pm.register(plugin, name=name)
        logger.debug("Registered plugin", name=name or str(plugin))

    def unregister(self, plugin: Any) -> None:
        self._pm.unregister(plugin)

    @property
    def hook(self) -> Any:
        return self._pm.hook

    def get_plugins(self) -> set[Any]:
        return self._pm.get_plugins()

    def is_registered(self, plugin: Any) -> bool:
        return self._pm.is_registered(plugin)
