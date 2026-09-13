from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sqlseed.core.constraints import ConstraintSolver
from sqlseed.core.enrichment import EnrichmentEngine
from sqlseed.core.expression import ExpressionEngine
from sqlseed.core.mapper import ColumnMapper
from sqlseed.core.plugin_mediator import PluginMediator
from sqlseed.core.schema import SchemaInferrer
from sqlseed.core.stream import DataStream
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter
from sqlseed.plugins.manager import PluginManager
from tests.conftest import create_simple_db

if TYPE_CHECKING:
    from sqlseed.core.column_dag import ColumnNode
    from sqlseed.core.transform import RowTransformFn


def make_stream(
    dag_nodes: list[ColumnNode],
    provider: Any,
    *,
    seed: int = 42,
    constraint_solver: ConstraintSolver | None = None,
    expr_engine: ExpressionEngine | None = None,
    transform_fn: RowTransformFn | None = None,
) -> DataStream:
    """Build a ``DataStream`` with the boilerplate defaults used across test_stream.py.

    Most tests in ``test_core/test_stream.py`` construct a ``DataStream`` with a
    fresh ``ExpressionEngine()``, fresh ``ConstraintSolver()``, and ``seed=42``.
    Centralizing that here removes ~16 CodeDuplication warnings flagged by
    CodeFlow without obscuring test intent — only the varying parts
    (``dag_nodes``, ``provider``, optionally a pre-configured ``constraint_solver``
    or ``transform_fn``) appear at call sites.

    Args:
        dag_nodes: The list of ``ColumnNode`` objects (already built via ``ColumnDAG``).
        provider: The data provider instance (``BaseProvider()``, ``MagicMock()``, etc.).
        seed: Deterministic seed; defaults to 42 to match the prior inline value.
        constraint_solver: Optional pre-configured solver (e.g. when a test
            pre-registers a value to force a collision). When ``None`` a fresh
            ``ConstraintSolver()`` is constructed.
        expr_engine: Optional pre-configured expression engine. When ``None`` a
            fresh ``ExpressionEngine()`` is constructed.
        transform_fn: Optional row transform callable passed straight through to
            ``DataStream``.

    Returns:
        A ready-to-use ``DataStream`` instance.
    """
    return DataStream(
        dag_nodes=dag_nodes,
        provider=provider,
        expr_engine=expr_engine or ExpressionEngine(),
        constraint_solver=constraint_solver or ConstraintSolver(),
        transform_fn=transform_fn,
        seed=seed,
    )


class EnrichmentContext:
    def __init__(self, adapter: RawSQLiteAdapter, engine: EnrichmentEngine, schema: SchemaInferrer) -> None:
        self.adapter = adapter
        self.engine = engine
        self.schema = schema


class MediatorContext:
    def __init__(self, adapter: RawSQLiteAdapter, mediator: PluginMediator, schema: SchemaInferrer) -> None:
        self.adapter = adapter
        self.mediator = mediator
        self.schema = schema


@pytest.fixture
def enrich_ctx(tmp_path: Any):
    db_path = str(tmp_path / "test.db")
    create_simple_db(db_path)

    adapter = RawSQLiteAdapter()
    adapter.connect(db_path)
    mapper = ColumnMapper()
    schema = SchemaInferrer(adapter)
    engine = EnrichmentEngine(adapter, mapper, schema)
    ctx = EnrichmentContext(adapter, engine, schema)
    yield ctx
    adapter.close()


@pytest.fixture
def mediator_ctx(tmp_path: Any):
    db_path = str(tmp_path / "test.db")
    create_simple_db(db_path)

    adapter = RawSQLiteAdapter()
    adapter.connect(db_path)
    schema = SchemaInferrer(adapter)
    plugins = PluginManager()
    plugins.load_plugins()
    mediator = PluginMediator(plugins, adapter, schema)
    ctx = MediatorContext(adapter, mediator, schema)
    yield ctx
    adapter.close()
