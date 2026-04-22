from __future__ import annotations

import pytest

from sqlseed.core.enrichment import EnrichmentEngine
from sqlseed.core.mapper import ColumnMapper
from sqlseed.core.plugin_mediator import PluginMediator
from sqlseed.core.schema import SchemaInferrer
from sqlseed.database.sqlite_utils_adapter import SQLiteUtilsAdapter
from sqlseed.plugins.manager import PluginManager
from tests.conftest import create_simple_db


class EnrichmentContext:
    def __init__(self, adapter: SQLiteUtilsAdapter, engine: EnrichmentEngine, schema: SchemaInferrer) -> None:
        self.adapter = adapter
        self.engine = engine
        self.schema = schema


class MediatorContext:
    def __init__(self, adapter: SQLiteUtilsAdapter, mediator: PluginMediator, schema: SchemaInferrer) -> None:
        self.adapter = adapter
        self.mediator = mediator
        self.schema = schema


@pytest.fixture
def enrich_ctx(tmp_path):
    db_path = str(tmp_path / "test.db")
    create_simple_db(db_path)

    adapter = SQLiteUtilsAdapter()
    adapter.connect(db_path)
    mapper = ColumnMapper()
    schema = SchemaInferrer(adapter)
    engine = EnrichmentEngine(adapter, mapper, schema)
    ctx = EnrichmentContext(adapter, engine, schema)
    yield ctx
    adapter.close()


@pytest.fixture
def mediator_ctx(tmp_path):
    db_path = str(tmp_path / "test.db")
    create_simple_db(db_path)

    adapter = SQLiteUtilsAdapter()
    adapter.connect(db_path)
    schema = SchemaInferrer(adapter)
    plugins = PluginManager()
    plugins.load_plugins()
    mediator = PluginMediator(plugins, adapter, schema)
    ctx = MediatorContext(adapter, mediator, schema)
    yield ctx
    adapter.close()
