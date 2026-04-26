from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PragmaProfile:
    synchronous: Any = None
    journal_mode: Any = None
    cache_size: Any = None
    temp_store: Any = None
    auto_vacuum: Any = None
    page_size: Any = None
    mmap_size: Any = None


class PragmaOptimizer:
    TEMP_STORE_MEMORY: str = "PRAGMA temp_store = MEMORY"

    def __init__(self, execute_fn: Any, fetch_pragma_fn: Any) -> None:
        self._execute = execute_fn
        self._fetch_pragma = fetch_pragma_fn
        self._original: PragmaProfile | None = None

    def preserve(self) -> None:
        self._original = PragmaProfile(
            synchronous=self._fetch_pragma("synchronous"),
            journal_mode=self._fetch_pragma("journal_mode"),
            cache_size=self._fetch_pragma("cache_size"),
            temp_store=self._fetch_pragma("temp_store"),
            auto_vacuum=self._fetch_pragma("auto_vacuum"),
            page_size=self._fetch_pragma("page_size"),
            mmap_size=self._fetch_pragma("mmap_size"),
        )
        logger.debug("Preserved PRAGMA config", config=self._original)

    def optimize(self, expected_rows: int | None = None) -> None:
        if expected_rows is None:
            expected_rows = 10000

        if expected_rows > 100000:
            self._apply_aggressive()
        elif expected_rows > 10000:
            self._apply_moderate()
        else:
            self._apply_light()

    def _apply_light(self) -> None:
        self._execute("PRAGMA synchronous = NORMAL")
        self._execute(self.TEMP_STORE_MEMORY)
        self._execute("PRAGMA cache_size = -8000")
        logger.debug("Applied LIGHT PRAGMA optimization")

    def _apply_moderate(self) -> None:
        self._execute("PRAGMA synchronous = OFF")
        self._execute("PRAGMA journal_mode = MEMORY")
        self._execute(self.TEMP_STORE_MEMORY)
        self._execute("PRAGMA cache_size = -16000")
        self._execute("PRAGMA mmap_size = 268435456")
        logger.debug("Applied MODERATE PRAGMA optimization")

    def _apply_aggressive(self) -> None:
        self._execute("PRAGMA synchronous = OFF")
        self._execute("PRAGMA journal_mode = OFF")
        self._execute(self.TEMP_STORE_MEMORY)
        self._execute("PRAGMA cache_size = -32000")
        self._execute("PRAGMA mmap_size = 536870912")
        self._execute("PRAGMA page_size = 4096")
        logger.debug("Applied AGGRESSIVE PRAGMA optimization")

    def restore(self) -> None:
        if self._original is None:
            return

        for attr in (
            "synchronous",
            "journal_mode",
            "cache_size",
            "temp_store",
            "auto_vacuum",
            "page_size",
            "mmap_size",
        ):
            value = getattr(self._original, attr)
            if value is not None and (
                isinstance(value, (int, float)) or (isinstance(value, str) and re.match(r"^[a-zA-Z0-9_-]+$", value))
            ):
                try:
                    self._execute(f"PRAGMA {attr} = {value}")
                except Exception:
                    logger.debug("Failed to restore PRAGMA", attr=attr, value=value)

        logger.debug("Restored original PRAGMA config")
        self._original = None
