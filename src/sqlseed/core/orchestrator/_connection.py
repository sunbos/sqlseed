"""Connection mixin: lifecycle, adapter creation, and component accessors.

Separated from the original ``orchestrator.py`` to isolate the concerns of
database connection management, adapter creation, component wiring, and
the context manager protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlseed._utils.logger import get_logger
from sqlseed.core.enrichment import EnrichmentEngine
from sqlseed.core.plugin_mediator import PluginMediator
from sqlseed.core.relation import RelationResolver, SharedPool
from sqlseed.core.schema import SchemaInferrer
from sqlseed.core.schema_fallback import SchemaFallbackGenerator
from sqlseed.core.unique_adjuster import UniqueAdjuster
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

from ._common import CoreCtx, ExtCtx, _is_db_url

if TYPE_CHECKING:
    from sqlseed._utils.metrics import MetricsCollector
    from sqlseed.config.models import CustomColumnMappings
    from sqlseed.core.mapper import ColumnMapper
    from sqlseed.database._protocol import DatabaseAdapter
    from sqlseed.generators.registry import ProviderRegistry
    from sqlseed.plugins.manager import PluginManager

    from . import DataOrchestrator

logger = get_logger(__name__)


class ConnectionMixin:
    """Mixin providing database connection lifecycle and component accessors.

    Owns the orchestrator's ``__init__``, adapter creation, lazy connection
    initialization, all ``_core``/``_ext`` property accessors, and the
    context manager protocol. Expects to be composed with the other
    orchestrator mixins in :class:`DataOrchestrator`.
    """

    # Type hints for instance attributes set in __init__.
    _core: CoreCtx
    _ext: ExtCtx
    _db_path: str
    _provider_name: str
    _locale: str
    _optimize_pragma: bool
    _connected: bool
    _custom_column_mappings: CustomColumnMappings | None

    def __init__(
        self,
        db_path: str,
        *,
        provider_name: str = "mimesis",
        locale: str = "en_US",
        optimize_pragma: bool = True,
        associations: list[Any] | None = None,
        custom_column_mappings: CustomColumnMappings | None = None,
    ) -> None:
        self._db_path = db_path
        self._provider_name = provider_name
        self._locale = locale
        self._optimize_pragma = optimize_pragma
        self._custom_column_mappings = custom_column_mappings

        db_adapter = self._create_adapter()
        shared_pool = SharedPool()
        self._core = CoreCtx(
            db=db_adapter,
            schema=SchemaInferrer(db_adapter),
            relation=RelationResolver(db_adapter, shared_pool),
            shared_pool=shared_pool,
        )
        self._ext = ExtCtx(
            unique_adjuster=UniqueAdjuster(self._core.mapper),
            schema_fallback=SchemaFallbackGenerator(),
        )
        self._connected = False

        if associations:
            self._relation.set_associations(associations)

    @property
    def _db(self) -> DatabaseAdapter:
        if self._core.db is None:
            raise RuntimeError("Database adapter not initialized. Call _ensure_connected() first.")
        return self._core.db

    @property
    def database_adapter(self) -> DatabaseAdapter:
        """Public accessor for the database adapter.

        Use this instead of the private ``_db`` attribute for external code
        that needs direct adapter access (e.g., AI plugin schema analysis).
        """
        return self._db

    @property
    def _schema(self) -> SchemaInferrer:
        if self._core.schema is None:
            raise RuntimeError("SchemaInferrer not initialized. Call _ensure_connected() first.")
        return self._core.schema

    @property
    def _mapper(self) -> ColumnMapper:
        return self._core.mapper

    @property
    def _relation(self) -> RelationResolver:
        rel = self._core.relation
        if rel is None:
            raise RuntimeError("RelationResolver not initialized. Call _ensure_connected() first.")
        return rel

    @property
    def _shared_pool(self) -> SharedPool:
        return self._core.shared_pool

    @property
    def _registry(self) -> ProviderRegistry:
        return self._ext.registry

    @property
    def _plugins(self) -> PluginManager:
        return self._ext.plugins

    @property
    def _plugin_mediator(self) -> PluginMediator | None:
        return self._ext.plugin_mediator

    @_plugin_mediator.setter
    def _plugin_mediator(self, value: PluginMediator | None) -> None:
        self._ext.plugin_mediator = value

    @property
    def _enrichment(self) -> EnrichmentEngine | None:
        return self._ext.enrichment

    @_enrichment.setter
    def _enrichment(self, value: EnrichmentEngine | None) -> None:
        self._ext.enrichment = value

    @property
    def _unique_adjuster(self) -> UniqueAdjuster:
        adj = self._ext.unique_adjuster
        if adj is None:
            raise RuntimeError("UniqueAdjuster not initialized. Call _ensure_connected() first.")
        return adj

    @property
    def _schema_fallback(self) -> SchemaFallbackGenerator | None:
        return self._ext.schema_fallback

    @property
    def _metrics(self) -> MetricsCollector:
        return self._ext.metrics

    @classmethod
    def from_config(cls, config: Any) -> DataOrchestrator:
        """Construct a DataOrchestrator from a GeneratorConfig instance."""
        return cast(
            "DataOrchestrator",
            cls(
                db_path=config.connection_target,
                provider_name=config.provider.value,
                locale=config.locale,
                optimize_pragma=config.optimize_pragma,
                associations=config.associations if config.associations else None,
                custom_column_mappings=config.custom_column_mappings,
            ),
        )

    def _create_adapter(self) -> DatabaseAdapter:
        # Phase 4: uniformly use SQLAlchemyAdapter (SQLAlchemy is a core dependency).
        # SQLAlchemyAdapter automatically handles database URLs (postgresql://, etc.)
        # and SQLite file paths, shielding dialect differences via the Dialect abstraction.
        if _is_db_url(self._db_path):
            logger.debug("Using SQLAlchemyAdapter (database URL)", db_target=self._db_path)
        else:
            logger.debug("Using SQLAlchemyAdapter (SQLite file)", db_target=self._db_path)
        return SQLAlchemyAdapter()

    def _ensure_connected(self) -> None:
        if not self._connected:
            self._db.connect(self._db_path)
            self._connected = True
            self._enrichment = EnrichmentEngine(self._db, self._mapper, self._schema)
            self._plugins.load_plugins()
            self._plugins.hook.sqlseed_register_providers(registry=self._registry)
            self._plugins.hook.sqlseed_register_column_mappers(mapper=self._mapper)
            # Load user-defined custom column mappings from YAML config.
            # These rules have higher priority than built-in rules but are
            # registered after plugin hooks so plugins can also contribute.
            if self._custom_column_mappings is not None:
                self._mapper.load_custom_mappings(self._custom_column_mappings)
            self._registry.register_from_entry_points()
            try:
                self._registry.ensure_provider(self._provider_name)
                self._registry.set_default(self._provider_name)
            except (ImportError, ValueError):
                logger.warning(
                    "Provider not available, falling back to 'base'",
                    provider_name=self._provider_name,
                )
                self._provider_name = "base"
                # Make the fallback durable: subsequent get() calls without an
                # explicit name (which use the default) must resolve to "base"
                # rather than re-attempting the failed provider.
                self._registry.set_default("base")
            provider = self._registry.get(self._provider_name)
            try:
                provider.set_locale(self._locale)
            except (ValueError, TypeError) as exc:
                # Invalid locale string (e.g. "en_XX") may crash the provider.
                # Fall back to a safe default and log a warning so the user can
                # correct the locale without the whole run failing.
                logger.warning(
                    "Invalid locale, falling back to provider default",
                    locale=self._locale,
                    provider=self._provider_name,
                    error=str(exc),
                )
                provider.set_locale("en_US" if self._provider_name == "faker" else "en")
            self._plugin_mediator = PluginMediator(self._plugins, self._db, self._schema)

    def close(self) -> None:
        """Close the database connection if it is currently open."""
        if self._connected:
            self._db.close()
            self._connected = False

    def __enter__(self) -> DataOrchestrator:
        self._ensure_connected()
        return cast("DataOrchestrator", self)

    def __exit__(self, exc_type: type | None, exc_val: Exception | None, exc_tb: Any) -> None:
        self.close()
