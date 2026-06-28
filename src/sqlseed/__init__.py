"""sqlseed — declarative SQLite/multi-database test data generation toolkit.

Public API: fill, connect, fill_from_config, preview, load_config.
"""
from __future__ import annotations

from typing import Any

from sqlseed._utils.logger import get_logger
from sqlseed._version import __version__
from sqlseed.config.loader import load_config
from sqlseed.config.models import (
    ColumnConfig,
    GeneratorConfig,
    ProviderType,
    TableConfig,
)
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.core.result import GenerationResult

__all__ = [
    "ColumnConfig",
    "DataOrchestrator",
    "GenerationResult",
    "GeneratorConfig",
    "ProviderType",
    "TableConfig",
    "__version__",
    "connect",
    "fill",
    "fill_from_config",
    "load_config",
    "preview",
]

logger = get_logger(__name__)


def fill(
    db_path: str | None = None,
    *,
    url: str | None = None,
    table: str,
    count: int = 1000,
    columns: dict[str, Any] | None = None,
    provider: str = "mimesis",
    locale: str = "en_US",
    seed: int | None = None,
    batch_size: int = 5000,
    clear_before: bool = False,
    optimize_pragma: bool = True,
    enrich: bool = False,
    transform: str | None = None,
    skip_ai: bool = True,
) -> GenerationResult:
    """Fill a single table with zero configuration.

    Two mutually exclusive connection modes are supported:
    - ``fill("app.db", table="users", count=1000)`` — SQLite file path
    - ``fill(url="postgresql://user:pass@host/db", table="users", count=1000)`` — database URL

    Args:
        db_path: SQLite database file path (mutually exclusive with ``url``).
        url: Database URL, e.g. ``postgresql://user:pass@host/db`` (mutually exclusive with ``db_path``).

    Raises:
        ValueError: If neither ``db_path`` nor ``url`` is provided, or if both are provided.
    """
    target = _resolve_db_target(db_path, url)
    with DataOrchestrator(
        db_path=target,
        provider_name=provider,
        locale=locale,
        optimize_pragma=optimize_pragma,
    ) as orch:
        return orch.fill_table(
            table_name=table,
            count=count,
            columns=columns,
            seed=seed,
            batch_size=batch_size,
            clear_before=clear_before,
            enrich=enrich,
            transform=transform,
            skip_ai=skip_ai,
        )


def connect(
    db_path: str | None = None,
    *,
    url: str | None = None,
    provider: str = "mimesis",
    locale: str = "en_US",
    optimize_pragma: bool = True,
) -> DataOrchestrator:
    """Connect to a database and return a DataOrchestrator context manager.

    Two mutually exclusive connection modes are supported:
    - ``connect("app.db")`` — SQLite file path
    - ``connect(url="postgresql://user:pass@host/db")`` — database URL

    Args:
        db_path: SQLite database file path (mutually exclusive with ``url``).
        url: Database URL (mutually exclusive with ``db_path``).

    Raises:
        ValueError: If neither ``db_path`` nor ``url`` is provided, or if both are provided.
    """
    target = _resolve_db_target(db_path, url)
    return DataOrchestrator(
        db_path=target,
        provider_name=provider,
        locale=locale,
        optimize_pragma=optimize_pragma,
    )


def _resolve_db_target(db_path: str | None, url: str | None) -> str:
    """Resolve the database connection target; db_path and url are mutually exclusive.

    Args:
        db_path: SQLite file path.
        url: Database URL.

    Returns:
        Connection target string for DataOrchestrator.

    Raises:
        ValueError: If both are provided or neither is provided.
    """
    if db_path is not None and url is not None:
        raise ValueError("Cannot specify both db_path and url. Use one or the other.")
    if db_path is not None:
        return db_path
    if url is not None:
        return url
    raise ValueError("Either db_path or url must be provided.")


def fill_from_config(
    config_path: str,
    *,
    skip_ai: bool = True,
    clear_before: bool = False,
    count: int | None = None,
    provider: str | None = None,
    seed: int | None = None,
    batch_size: int | None = None,
    locale: str | None = None,
) -> list[GenerationResult]:
    """Load data generation config from a YAML/JSON file and fill multiple tables.

    All tables are filled in topological order (foreign key dependencies first).
    Global parameters in the config can be overridden via keyword arguments.

    Args:
        config_path: Path to the config file (YAML or JSON).
        skip_ai: Skip AI analysis (default True).
        clear_before: Clear tables before filling (default False).
        count: Override row count for all tables (None uses each table's config).
        provider: Override data provider (None uses config value).
        seed: Override random seed (None uses each table's config).
        batch_size: Override batch size (None uses each table's config).
        locale: Override locale (None uses config value).

    Returns:
        List of generation results per table, in topological order.
    """
    config = load_config(config_path)
    if provider is not None:
        config.provider = ProviderType(provider)
    if locale is not None:
        config.locale = locale
    results: list[GenerationResult] = []
    with DataOrchestrator.from_config(config) as orch:
        table_names = [tc.name for tc in config.tables]
        sorted_names = orch.get_topological_table_order(table_names)
        name_to_config = {tc.name: tc for tc in config.tables}
        total_tables = len(sorted_names)
        for idx, name in enumerate(sorted_names, 1):
            table_config = name_to_config[name]
            effective_count = count if count is not None else table_config.count
            effective_seed = seed if seed is not None else table_config.seed
            effective_batch_size = batch_size if batch_size is not None else table_config.batch_size
            logger.info(
                "Filling table",
                table=table_config.name,
                count=effective_count,
                progress=f"[{idx}/{total_tables}]",
            )
            result = orch.fill_table(
                table_name=table_config.name,
                count=effective_count,
                seed=effective_seed,
                batch_size=effective_batch_size,
                clear_before=clear_before or table_config.clear_before,
                column_configs=table_config.columns,
                transform=table_config.transform,
                enrich=table_config.enrich,
                skip_ai=skip_ai,
            )
            results.append(result)
    return results


def preview(
    db_path: str | None = None,
    *,
    url: str | None = None,
    table: str,
    count: int = 5,
    columns: dict[str, Any] | None = None,
    provider: str = "mimesis",
    locale: str = "en_US",
    seed: int | None = None,
    enrich: bool = False,
    transform: str | None = None,
) -> list[dict[str, Any]]:
    """Preview generated data without writing to the database.

    Two mutually exclusive connection modes are supported:
    - ``preview("app.db", table="users")`` — SQLite file path
    - ``preview(url="postgresql://...", table="users")`` — database URL

    Args:
        db_path: SQLite database file path (mutually exclusive with ``url``).
        url: Database URL (mutually exclusive with ``db_path``).

    Raises:
        ValueError: If neither ``db_path`` nor ``url`` is provided, or if both are provided.
    """
    target = _resolve_db_target(db_path, url)
    with DataOrchestrator(
        db_path=target,
        provider_name=provider,
        locale=locale,
        optimize_pragma=False,
    ) as orch:
        return orch.preview_table(
            table_name=table,
            count=count,
            columns=columns,
            seed=seed,
            enrich=enrich,
            transform=transform,
        )
