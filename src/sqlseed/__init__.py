from __future__ import annotations

from typing import Any

from sqlseed._utils.logger import get_logger
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

logger = get_logger(__name__)


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
    enrich: bool = False,
    transform: str | None = None,
    skip_ai: bool = False,
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
            enrich=enrich,
            transform=transform,
            skip_ai=skip_ai,
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


def fill_from_config(config_path: str, *, skip_ai: bool = False) -> list[GenerationResult]:
    config = load_config(config_path)
    results: list[GenerationResult] = []
    with DataOrchestrator.from_config(config) as orch:
        table_names = [tc.name for tc in config.tables]
        sorted_names = orch.get_topological_table_order(table_names)
        name_to_config = {tc.name: tc for tc in config.tables}
        total_tables = len(sorted_names)
        for idx, name in enumerate(sorted_names, 1):
            table_config = name_to_config[name]
            logger.info(
                "Filling table",
                table=table_config.name,
                count=table_config.count,
                progress=f"[{idx}/{total_tables}]",
            )
            result = orch.fill_table(
                table_name=table_config.name,
                count=table_config.count,
                seed=table_config.seed,
                batch_size=table_config.batch_size,
                clear_before=table_config.clear_before,
                column_configs=table_config.columns,
                transform=table_config.transform,
                enrich=table_config.enrich,
                skip_ai=skip_ai,
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
    enrich: bool = False,
    transform: str | None = None,
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
            enrich=enrich,
            transform=transform,
        )
