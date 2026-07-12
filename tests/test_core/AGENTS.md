<!-- Parent: ../AGENTS.md -->
<!-- Last updated: 2026-07-12 -->

# test_core

## Purpose

Unit tests for core engine components. Covers DAG, constraint solving, enum enrichment, expression evaluation, uniqueness adjustment, and plugin mediation.

## Key Files

| File | Description |
|------|-------------|
| `conftest.py` | Local fixtures for core modules (enrich_ctx, mediator_ctx, etc.) |
| `test_column_dag.py` | ColumnDAG topological sort and dependency resolution tests |
| `test_constraints.py` | ConstraintSolver uniqueness constraint and backtracking tests |
| `test_enrichment.py` | EnrichmentEngine enum column enrichment tests |
| `test_expression.py` | ExpressionEngine expression evaluation tests |
| `test_plugin_mediator.py` | PluginMediator plugin interaction tests |
| `test_stream.py` | DataStream batch generation tests |
| `test_transform.py` | User-defined transform script loading tests |
| `test_unique_adjuster.py` | UniqueAdjuster uniqueness adjustment tests |

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
