<!-- Parent: ../AGENTS.md -->
<!-- Last updated: 2026-08-30 -->

# test_core

## Purpose

Unit tests for core engine components. Covers DAG, constraint solving, enum enrichment, expression evaluation, uniqueness adjustment, and plugin mediation. 14 files, 247 test functions.

## Key Files

| File | Tests | Description |
|------|------:|-------------|
| `conftest.py` | — | Local fixtures for core modules (enrich_ctx, mediator_ctx, etc.) |
| `test_stream.py` | 53 | DataStream batch generation + constraint backtracking |
| `test_check_adapt.py` | 33 | CheckAdapter param clamping (overlap/disjoint) |
| `test_check_parser.py` | 30 | CheckConstraintParser CHECK parsing |
| `test_unique_adjuster.py` | 28 | UniqueAdjuster adjustment (incl. TestAdjustChoiceFallback pattern) |
| `test_constraints.py` | 21 | ConstraintSolver backtracking (probabilistic set mode) |
| `test_expression.py` | 18 | ExpressionEngine sandbox + timeout |
| `test_features.py` | 17 | StructuralFeatureExtractor normalization |
| `test_schema_fallback.py` | 13 | SchemaFallbackGenerator |
| `test_plugin_mediator.py` | 9 | PluginMediator interactions |
| `test_column_dag.py` | 8 | ColumnDAG topological sort + cycles |
| `test_enrichment.py` | 7 | EnrichmentEngine enum patterns |
| `test_orchestrator_schema_fallback.py` | 5 | Fallback integration in _resolve_specs |
| `test_transform.py` | 5 | User transform script loading |
| `test_unique_exclude_integration.py` | 5 | exclude_values end-to-end |

## For AI Agents

### Working In This Directory

- DAG tests must cover circular dependency detection
- Constraint solver tests must cover large dataset scenarios (probabilistic set mode)
- Expression engine tests must cover safety sandbox boundaries
- Enrichment tests verify enum pattern detection from existing data distribution

### Testing Requirements

```bash
pytest tests/test_core/
```

### Common Patterns

- Use local fixtures in `conftest.py` to create test core component instances

## Dependencies

### Internal

- `src/sqlseed/core/`

### External

- `pytest>=8.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
