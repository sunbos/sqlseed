"""structlog configuration for sqlseed.

Centralized structured logging setup. The module auto-configures structlog on
import so that ``import sqlseed`` is sufficient to get properly formatted
log output — callers do not need to explicitly call ``configure_logging()``.

Output is written to **stderr** (not stdout) so that log lines never interleave
with data piped to stdout (e.g. ``sqlseed inspect`` JSON output).

``cache_logger_on_first_use=True`` is enabled for performance: structlog
wraps each logger in a bound callable on first use and reuses it thereafter.
The trade-off is that subsequent ``configure_logging()`` calls will not
affect loggers that have already been used — acceptable for sqlseed's
CLI-driven usage pattern where configuration happens once at startup.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog with sqlseed's standard processor chain.

    Args:
        level: Logging level name (e.g. ``"INFO"``, ``"DEBUG"``).
               Resolved via ``getattr(logging, level.upper(), logging.INFO)``.
    """
    structlog.configure(
        processors=[
            # --- Context ---
            structlog.contextvars.merge_contextvars,
            # --- Log level ---
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            # --- Formatting ---
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO),
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


_env_log_level = os.environ.get("SQLSEED_LOG_LEVEL", "WARNING").upper()
configure_logging(_env_log_level)


def get_logger(name: str | None = None) -> Any:
    """Return a structlog logger bound to *name*.

    The return type is ``Any`` because structlog loggers are dynamic proxies
    (bound wrappers); strong-typing them provides little benefit and would
    require importing structlog in every type-checking context.
    """
    return structlog.get_logger(name)
