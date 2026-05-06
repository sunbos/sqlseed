from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog


def configure_logging(level: str = "INFO") -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
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
    return structlog.get_logger(name)
