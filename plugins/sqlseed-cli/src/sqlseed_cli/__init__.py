"""Public API exports for the sqlseed-cli package.

This package provides the ``sqlseed`` console command. The entry point
``sqlseed = "sqlseed_cli:main"`` is declared in ``pyproject.toml``.

AI subcommand injection
-----------------------
Third-party packages (notably ``sqlseed-ai``) may register additional CLI
subcommands by exposing an entry point in the ``sqlseed.cli_commands``
group. Each entry point must resolve to a callable with the signature
``register(cli_group: click.Group) -> None``. This module discovers and
invokes all such callables at import time so that installing
``sqlseed-ai`` is sufficient to make ``ai-suggest`` appear under the
``sqlseed`` command — no source-level import is required.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points

from sqlseed_cli.main import cli, main

__all__ = ["cli", "main"]


def _register_plugin_commands() -> None:
    """Discover and register CLI subcommands contributed by other packages.

    Iterates the ``sqlseed.cli_commands`` entry-point group. Each entry
    point resolves to a callable ``register(cli_group: click.Group) -> None``.
    Failures are silently ignored so a broken plugin cannot crash the CLI;
    a debug-level log message is emitted for diagnostics.
    """
    eps = entry_points(group="sqlseed.cli_commands")

    for ep in eps:
        try:
            register = ep.load()
            register(cli)
        except (
            ImportError,
            AttributeError,
            TypeError,
            ValueError,
            RuntimeError,
            OSError,
        ):
            # A failing plugin must never break the core CLI; silently skip.
            # Users who need diagnostics can set SQLSEED_LOG_LEVEL=DEBUG.
            # Specific exception types are caught rather than bare Exception
            # to avoid suppressing BaseException subclasses (KeyboardInterrupt,
            # SystemExit) and to make the resilience contract explicit.
            logging.getLogger(__name__).debug("Failed to load CLI plugin entry point", extra={"entry_point": ep.name})


_register_plugin_commands()
