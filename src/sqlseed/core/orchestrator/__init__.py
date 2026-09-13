"""Data orchestration engine, coordinating schema inference, column mapping, relation resolution,
constraint solving, enrichment, and database writes.

DataOrchestrator serves as the core entry point, wiring together SchemaInferrer,
ColumnMapper, RelationResolver, ConstraintSolver, EnrichmentEngine and other components
to complete the full flow from schema inference to batch data writes. Production
environments uniformly use SQLAlchemyAdapter, and all database exceptions are of
sqlalchemy.exc.* types.

The implementation is split across four mixin modules, each owning a single
concern:

* :mod:`._connection` — lifecycle, adapter creation, component accessors, context manager.
* :mod:`._specs` — generator spec resolution, stream building, AI/template application.
* :mod:`._generation` — batch generation, fill, and preview entry points.
* :mod:`._query` — schema introspection, mapping diagnostics, direct SQL execution.

:class:`DataOrchestrator` composes all of the above via multiple inheritance.
"""

from __future__ import annotations

# Shared context dataclasses and helpers live in _common.py to avoid a
# circular import between the package __init__ and the mixin submodules.
# _is_db_url is re-exported here because tests/test_orchestrator_adapter.py
# imports it from this package (public API surface for the helper).
from ._common import CoreCtx, ExtCtx, _is_db_url

# Import mixins after the shared definitions are available.
from ._connection import ConnectionMixin
from ._generation import GenerationMixin
from ._query import QueryMixin
from ._specs import SpecResolverMixin

__all__ = [
    "CoreCtx",
    "DataOrchestrator",
    "ExtCtx",
    "_is_db_url",
]


class DataOrchestrator(
    ConnectionMixin,
    SpecResolverMixin,
    GenerationMixin,
    QueryMixin,
):
    """Data orchestration engine, wiring together schema inference, column mapping,
    relation resolution, and batch writes.

    Manages core components (schema, mapper, relation) and extension components
    (registry, plugins, enrichment) via two context groups CoreCtx/ExtCtx.
    Supports the context manager protocol to ensure controllable connection lifecycle.
    Production environments uniformly use SQLAlchemyAdapter to shield multi-database dialect differences.
    """
