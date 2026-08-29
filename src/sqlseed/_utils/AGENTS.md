<!-- Parent: ../AGENTS.md -->

# _utils

**Last updated:** 2026-08-30

## Purpose

Cross-module shared low-level utility functions. Includes logging, metrics, progress bars, cache paths, and SQL safety. 6 files.

## Key Files

| File | Lines | Key symbols | Description |
|------|------:|--------------|-------------|
| `progress.py` | 423 | `ProgressBackend`, `NullProgressBackend`, `RichProgressBackend`, `TqdmNotebookBackend`, `create_progress()` | three-backend progress bar factory: Null (disabled) / Rich (terminal, ASCII fallback) / tqdm (Jupyter), auto-selected by runtime environment |
| `paths.py` | 105 | `get_cache_dir()`, `validate_db_target()`, `validate_table_name()` | platform-standard cache dir (`SQLSEED_CACHE_DIR` env override), shared by SnapshotManager and AiConfigRefiner; validators shared by both MCP server packages |
| `sql_safe.py` | 84 | `_sanitize_identifier()`, `quote_identifier()`, `validate_table_name()`, `build_insert_sql()` | SQL injection protection three layers: validate / quote / build; double-quote escaping, rejects `; \n \r '` but allows `-` |
| `metrics.py` | 81 | `MetricEntry`, `MetricsCollector` | count/total/min/max/avg aggregate statistics, single-pass traversal |
| `logger.py` | 67 | `configure_logging()`, `get_logger()` | structlog config, auto-configures on module import, outputs to stderr |

## For AI Agents

### Working In This Directory

- `sql_safe.py` is a security-critical module; modifications require extreme caution, any changes must pass security review
- Logging uniformly uses structlog; all modules obtain loggers via `get_logger(__name__)`, do not use the standard library `logging`
- When adding new utility functions, consider whether they are truly shared by multiple modules; functions used by a single module should be placed in the corresponding module
- `MetricsCollector` uses dataclass to store metric entries, supports filtering by name and aggregate statistics

### Testing Requirements

```bash
pytest tests/test_utils/
```

### Common Patterns

- `get_logger(__name__)` obtains a module-level logger
- `sql_safe` module provides three layers of protection: validate, quote, build
- `create_progress()` auto-selects backend by environment: Jupyter→tqdm, terminal→Rich (ASCII fallback for GBK encoding), disabled→Null

## Dependencies

### Internal

- None (low-level module, does not depend on other internal modules)

### External

- `structlog>=24.0` — structured logging
- `rich>=13.0` — progress bar (terminal backend)
- `tqdm` — progress bar (Jupyter backend, optional, installed via `sqlseed[notebook]`)

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
