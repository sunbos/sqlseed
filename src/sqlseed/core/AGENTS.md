# CORE ORCHESTRATION LAYER

**Last updated:** 2026-07-12

## OVERVIEW

Central orchestration: schema inference, column mapping, constraint solving, data streaming.

## STRUCTURE

```
core/
├── __init__.py          # Public API exports: DataOrchestrator, ColumnMapper, GeneratorSpec, DataStream, etc.
├── orchestrator/        # DataOrchestrator package (4 mixins + shared _common):
│   ├── __init__.py      # DataOrchestrator class (composes 4 mixins via multiple inheritance)
│   ├── _common.py       # CoreCtx, ExtCtx, _is_db_url() — shared defs to avoid circular import
│   ├── _connection.py   # ConnectionMixin — init, adapter, connect, properties, lifecycle
│   ├── _specs.py        # SpecResolverMixin — resolve_specs, build_stream, prepare_specs
│   ├── _generation.py   # GenerationMixin — fill_table, preview_table, batch insert
│   └── _query.py        # QueryMixin — schema context, SQL execute/query, table info
├── mapper.py            # ColumnMapper 9-level strategy chain
├── schema.py            # SchemaInferrer — column info, indexes, distribution
├── check_parser.py      # CheckConstraintParser + ParsedCheck — single-column CHECK → generator hints
├── schema_fallback.py   # SchemaFallbackGenerator — pure schema-semantics fallback, zero business logic
├── features.py          # Normalized structural features for cross-DB schema analysis
├── relation.py          # RelationResolver + SharedPool — FK resolution
├── column_dag.py        # ColumnDAG — derive_from dependency graph
├── expression.py        # ExpressionEngine — simpleeval sandbox
├── constraints.py       # ConstraintSolver — unique constraint backtracking
├── enrichment.py        # EnrichmentEngine — 19 enum patterns
├── unique_adjuster.py   # UniqueAdjuster — auto-adjust unique specs
├── transform.py         # load_transform() function — user script dynamic loading
├── stream.py            # DataStream — batch generation + constraint backtracking
├── plugin_mediator.py   # PluginMediator — plugin ↔ core bridge
└── result.py            # GenerationResult dataclass
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Public API exports | `__init__.py` | Exports DataOrchestrator, ColumnMapper, GeneratorSpec, DataStream, RelationResolver, GenerationResult, SchemaInferrer, CheckConstraintParser, ParsedCheck, SchemaFallbackGenerator |
| Add fill logic | `orchestrator/_generation.py` | DataOrchestrator.fill_table() |
| Modify mapping | `mapper.py` | ColumnMapper.map_columns() — 9-level chain |
| Add schema info | `schema.py` | SchemaInferrer.get_column_info() |
| Parse CHECK constraints | `check_parser.py` | CheckConstraintParser, ParsedCheck |
| Schema-only fallback | `schema_fallback.py` | SchemaFallbackGenerator — called when mapping yields nothing |
| Handle FK | `relation.py` | RelationResolver.resolve_foreign_keys() |
| Add derive_from | `column_dag.py` | ColumnDAG.build() — topological sort |
| Modify expressions | `expression.py` | ExpressionEngine — 26 safe functions |
| Add constraint | `constraints.py` | ConstraintSolver — retry logic |
| Add enum pattern | `enrichment.py` | EnrichmentEngine — 19 patterns |
| Batch generation | `stream.py` | DataStream.generate() — yields batches |
| Add plugin hook | `plugin_mediator.py` | PluginMediator.apply_batch_transforms(), apply_template_pool() (generic only; apply_ai_suggestions moved to sqlseed-ai/ai_mediator.py in Phase C) |

## CONVENTIONS

- **Context manager**: DataOrchestrator uses `__enter__`/`__exit__`
- **Property access**: Private via `self._core.*` and `self._ext.*`
- **Error handling**: Catch `ValueError, RuntimeError, OSError, sqlalchemy.exc.OperationalError` (alias `SAOperationalError`) / `sqlalchemy.exc.IntegrityError` (alias `SAIntegrityError`)
- **Exception catching**: Production environments use SQLAlchemyAdapter, all database exceptions are `sqlalchemy.exc.*`; do not catch `sqlite3.*` (RawSQLiteAdapter is only for zero-dependency tests)
- **Metrics**: Record via `self._metrics.record(key, value)`
- **Progress**: Rich progress bars via `create_progress()`

## ANTI-PATTERNS

- **NEVER** call DB directly from orchestrator for data operations → use `self._db` property (except `execute()` for direct SQL)
- **NEVER** skip `validate_table_name()` before table operations
- **ALWAYS** call `_ensure_connected()` before any DB operation
- **ALWAYS** use `contextlib.suppress()` for non-critical errors
