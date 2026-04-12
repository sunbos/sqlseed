from __future__ import annotations

from typing import Any

from sqlseed._version import __version__

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

from sqlseed.config.loader import load_config
from sqlseed.config.models import (
    ColumnConfig,
    GeneratorConfig,
    ProviderType,
    TableConfig,
)
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.core.result import GenerationResult


def fill(
    db_path: str,
    *,
    table: str,
    count: int = 1000,
    columns: dict[str, Any] | None = None,
    provider: str = "mimesis",
    locale: str = "en_US",
    seed: int | None = None,
    batch_size: int = 5000,
    clear_before: bool = False,
    optimize_pragma: bool = True,
) -> GenerationResult:
    with DataOrchestrator(
        db_path=db_path,
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
        )


def connect(
    db_path: str,
    *,
    provider: str = "mimesis",
    locale: str = "en_US",
    optimize_pragma: bool = True,
) -> DataOrchestrator:
    return DataOrchestrator(
        db_path=db_path,
        provider_name=provider,
        locale=locale,
        optimize_pragma=optimize_pragma,
    )


def fill_from_config(config_path: str) -> list[GenerationResult]:
    config = load_config(config_path)
    results: list[GenerationResult] = []
    with DataOrchestrator(
        db_path=config.db_path,
        provider_name=config.provider.value,
        locale=config.locale,
        optimize_pragma=config.optimize_pragma,
    ) as orch:
        for table_config in config.tables:
            result = orch.fill_table(
                table_name=table_config.name,
                count=table_config.count,
                seed=table_config.seed,
                batch_size=table_config.batch_size,
                clear_before=table_config.clear_before,
                column_configs=table_config.columns,
            )
            results.append(result)
    return results


def preview(
    db_path: str,
    *,
    table: str,
    count: int = 5,
    columns: dict[str, Any] | None = None,
    provider: str = "mimesis",
    locale: str = "en_US",
    seed: int | None = None,
) -> list[dict[str, Any]]:
    with DataOrchestrator(
        db_path=db_path,
        provider_name=provider,
        locale=locale,
        optimize_pragma=False,
    ) as orch:
        return orch.preview_table(
            table_name=table,
            count=count,
            columns=columns,
            seed=seed,
        )
