"""Recoverable generation failures, including the active connection's DBAPI errors."""

from __future__ import annotations

import re
import sqlite3
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError
from sqlseed.generators._protocol import ConfigurationError, GenerationError, UnknownGeneratorError

if TYPE_CHECKING:
    from sqlseed.core.orchestrator import DataOrchestrator


def generation_errors(
    orch: DataOrchestrator | None = None, *, additional: tuple[type[Exception], ...] = ()
) -> tuple[type[Exception], ...]:
    """Describe core's validation/provider contract and the loaded database driver.

    Raw cursor failures retain their native driver class. Reading that class
    avoids importing optional drivers or opening a connection just to catch an
    error. Programmer errors outside these operational contracts propagate.
    """
    errors: tuple[type[Exception], ...] = (
        ConfigurationError,
        GenerationError,
        UnknownGeneratorError,
        ValueError,
        TypeError,
        RuntimeError,
        OSError,
        ArithmeticError,
        re.error,
        SQLAlchemyError,
        sqlite3.Error,
    )
    if orch is not None and (engine := getattr(orch.database_adapter, "_engine", None)) is not None:
        error_type = engine.dialect.loaded_dbapi.Error
        if isinstance(error_type, type) and issubclass(error_type, Exception):
            errors += (error_type,)
    return errors + additional
