# CORE ORCHESTRATION LAYER

## OVERVIEW

Central orchestration: schema inference, column mapping, constraint solving, data streaming.

## STRUCTURE

```
core/
├── orchestrator.py      # DataOrchestrator main engine (557 lines)
├── mapper.py            # ColumnMapper 7-level strategy chain
├── schema.py            # SchemaInferrer — column info, indexes, distribution
├── relation.py          # RelationResolver + SharedPool — FK resolution
├── column_dag.py        # ColumnDAG — derive_from dependency graph
├── expression.py        # ExpressionEngine — simpleeval sandbox
├── constraints.py       # ConstraintSolver — unique constraint backtracking
├── enrichment.py        # EnrichmentEngine — 19 enum patterns
├── unique_adjuster.py   # UniqueAdjuster — auto-adjust unique specs
├── transform.py         # TransformLoader — user script dynamic loading
├── plugin_mediator.py   # PluginMediator — plugin ↔ core bridge
└── result.py            # GenerationResult dataclass
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add fill logic | `orchestrator.py` | DataOrchestrator.fill_table() |
| Modify mapping | `mapper.py` | ColumnMapper.map_columns() — 7-level chain |
| Add schema info | `schema.py` | SchemaInferrer.get_column_info() |
| Handle FK | `relation.py` | RelationResolver.resolve_foreign_keys() |
| Add derive_from | `column_dag.py` | ColumnDAG.build() — topological sort |
| Modify expressions | `expression.py` | ExpressionEngine — 21 safe functions |
| Add constraint | `constraints.py` | ConstraintSolver — retry logic |
| Add enum pattern | `enrichment.py` | EnrichmentEngine — 19 patterns |
| Add plugin hook | `plugin_mediator.py` | PluginMediator.apply_*() methods |

## CONVENTIONS

- **Context manager**: DataOrchestrator uses `__enter__`/`__exit__`
- **Property access**: Private via `self._core.*` and `self._ext.*`
- **Error handling**: Catch `ValueError, RuntimeError, OSError, sqlite3.OperationalError`
- **Metrics**: Record via `self._metrics.record(key, value)`
- **Progress**: Rich progress bars via `create_progress()`

## ANTI-PATTERNS

- **NEVER** call DB directly from orchestrator → use `self._db` property
- **NEVER** skip `validate_table_name()` before table operations
- **ALWAYS** call `_ensure_connected()` before any DB operation
- **ALWAYS** use `contextlib.suppress()` for non-critical errors
