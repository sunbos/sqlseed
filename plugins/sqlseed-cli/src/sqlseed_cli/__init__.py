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

from importlib.metadata import entry_points

from sqlseed_cli.main import cli, main

from sqlseed._utils.logger import get_logger

__all__ = ["cli", "main"]

_logger = get_logger(__name__)


def _register_plugin_commands() -> None:
    """Discover and register CLI subcommands contributed by other packages.

    Iterates the ``sqlseed.cli_commands`` entry-point group. Each entry
    point resolves to a callable ``register(cli_group: click.Group) -> None``.
    Failures are logged at WARNING level (not silently swallowed) so users
    can diagnose missing subcommands without setting SQLSEED_LOG_LEVEL=DEBUG.
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
        ) as exc:
            # A failing plugin must never break the core CLI, but a warning
            # makes the failure visible by default so users can diagnose
            # missing subcommands (e.g. ai-suggest not appearing because
            # sqlseed-ai failed to load). Specific exception types are caught
            # rather than bare Exception to avoid suppressing BaseException
            # subclasses (KeyboardInterrupt, SystemExit) and to make the
            # resilience contract explicit.
            _logger.warning(
                "Failed to load CLI plugin entry point",
                entry_point=ep.name,
                error=str(exc),
            )


_register_plugin_commands()
