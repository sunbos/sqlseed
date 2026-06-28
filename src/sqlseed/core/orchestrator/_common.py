"""Shared definitions for the orchestrator package.

Hosts ``CoreCtx`` / ``ExtCtx`` / ``_is_db_url`` so that mixin modules
(``_connection``, ``_specs``, ``_query``, ``_generation``) can import them
without creating a circular dependency on the package ``__init__``.

Previously these names lived in ``orchestrator/__init__.py`` and the mixins
imported them via ``from . import CoreCtx, ExtCtx, _is_db_url``. That worked
only because Python partially initializes the package module before importing
submodules, which made the import order fragile. Moving them here eliminates
the circular dependency entirely.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlseed._utils.metrics import MetricsCollector
from sqlseed.core.mapper import ColumnMapper
from sqlseed.core.relation import RelationResolver, SharedPool
from sqlseed.generators.registry import ProviderRegistry
from sqlseed.plugins.manager import PluginManager

if TYPE_CHECKING:
    from sqlseed.core.enrichment import EnrichmentEngine
    from sqlseed.core.plugin_mediator import PluginMediator
    from sqlseed.core.schema import SchemaInferrer
    from sqlseed.core.unique_adjuster import UniqueAdjuster
    from sqlseed.database._protocol import DatabaseAdapter


def _is_db_url(target: str) -> bool:
    """Determine whether the connection target is a database URL (with scheme) or a plain file path.

    URL examples: "postgresql://user:pass@host/db"
    File path examples: "/path/to/db.sqlite", "app.db"

    A SQLAlchemy URL must contain "://" (the scheme + authority/path separator).
    """
    return "://" in target


@dataclass
class CoreCtx:
    """Core context: shared database, schema, mapper, relation, and pool refs."""

    db: DatabaseAdapter | None = None
    schema: SchemaInferrer | None = None
    mapper: ColumnMapper = field(default_factory=ColumnMapper)
    relation: RelationResolver | None = None
    shared_pool: SharedPool = field(default_factory=SharedPool)


@dataclass
class ExtCtx:
    """Extension context: registry, plugins, mediator, enrichment, adjuster, metrics."""

    registry: ProviderRegistry = field(default_factory=ProviderRegistry)
    plugins: PluginManager = field(default_factory=PluginManager)
    plugin_mediator: PluginMediator | None = None
    enrichment: EnrichmentEngine | None = None
    unique_adjuster: UniqueAdjuster | None = None
    metrics: MetricsCollector = field(default_factory=MetricsCollector)


__all__ = ["CoreCtx", "ExtCtx", "_is_db_url"]
