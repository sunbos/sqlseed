"""Validate model candidates before merging or declaring a repair successful.

This checks configuration structure and builtin dispatch call contracts without
generating rows. Database constraints remain FastValidator's responsibility;
runtime values, native methods and custom providers are checked during execution.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, get_type_hints

from pydantic import TypeAdapter

from sqlseed.config.models import ColumnConfig, GeneratorConfig, ProviderType, TableConfig
from sqlseed.generators._dispatch import GeneratorDispatchMixin
from sqlseed.generators.registry import ProviderRegistry

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot


_CORE_GENERATORS = {"autoincrement", "foreign_key", "foreign_key_or_integer", "skip", "__enrich__"}


def validate_column_patch(patch: Any) -> dict[str, Any]:
    """Normalize the same column aliases/modes accepted by the core config loader."""
    return ColumnConfig.model_validate(patch).model_dump(exclude_unset=True, mode="json")


def validate_patch(patch: Any) -> dict[str, Any]:
    """Reject invalid containers and ambiguous names before dictionary-based merge."""
    if not isinstance(patch, dict) or not isinstance(patch.get("tables"), list):
        raise ValueError("Config validation: 'tables' must be a list")
    tables = [TableConfig.model_validate(table) for table in patch["tables"]]
    names = [table.name for table in tables]
    if len(names) != len(set(names)):
        raise ValueError("Config validation: duplicate table names")
    for table in tables:
        columns = [column.name for column in table.columns]
        if len(columns) != len(set(columns)):
            raise ValueError(f"Config validation: duplicate columns in {table.name}")
    return {"tables": [table.model_dump(exclude_unset=True, mode="json") for table in tables]}


def validate_candidate(config: dict[str, Any], snapshot: SchemaSnapshot) -> None:
    """Check schema names, config models and builtin generator signatures/types.

    Native and derived columns retain their separate execution modes. Custom
    providers own their extension-specific dispatch contract; this function does
    not load arbitrary entry points or execute any generator/native method.
    """
    model = GeneratorConfig.model_validate({"db_path": snapshot.db_path, "url": snapshot.url, **config})
    registry = ProviderRegistry()
    configured: set[ProviderType] = set()
    for table in model.tables:
        if (meta := snapshot.tables.get(table.name)) is None:
            raise ValueError(f"Config validation: unknown table {table.name}")
        for column in table.columns:
            if column.name not in meta.columns:
                raise ValueError(f"Config validation: unknown column {table.name}.{column.name}")
            _validate_candidate_column(column, table.name, model, registry, configured)


def _validate_candidate_column(
    column: ColumnConfig,
    table_name: str,
    model: GeneratorConfig,
    registry: ProviderRegistry,
    configured: set[ProviderType],
) -> None:
    """Check one builtin source while sharing provider setup across the candidate."""
    if column.derive_from or not column.generator or column.generator in _CORE_GENERATORS:
        return
    if (provider_name := column.provider or model.provider) == ProviderType.CUSTOM:
        return
    if (method_name := GeneratorDispatchMixin.GENERATOR_MAP.get(column.generator)) is None:
        raise ValueError(f"Config validation: unknown generator {column.generator!r}")
    provider = registry.ensure_provider(provider_name.value)
    if provider_name not in configured:
        provider.set_locale(model.locale)
        configured.add(provider_name)
    method = getattr(provider, method_name)
    _validate_builtin_params(column, table_name, method)


def _validate_builtin_params(column: ColumnConfig, table_name: str, method: Callable[..., Any]) -> None:
    """Validate bound builtin arguments without executing the generator.

    Raises:
        ValueError: When parameter binding or strict type validation fails.
    """
    try:
        bound = inspect.signature(method).bind(**column.params)
        hints = get_type_hints(method)
        for name, value in bound.arguments.items():
            annotation = hints.get(name, Any)
            TypeAdapter(annotation).validate_python(value, strict=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Config validation: invalid {column.generator} params for {table_name}.{column.name}: {exc}"
        ) from exc
