<!-- Parent: ../AGENTS.md -->

# _utils

**Generated:** 2026-06-21

## Purpose

Cross-module shared low-level utility functions. Includes logging, metrics, progress bars, cache paths, and SQL safety.

## Key Files

| File | Description |
|------|-------------|
| `logger.py` | structlog configuration, `configure_logging()` and `get_logger()` functions; auto-configures on module import, outputs to stderr |
| `metrics.py` | `MetricsCollector` performance metrics collection and aggregate statistics (count/total/min/max/avg), single-pass traversal |
| `paths.py` | `get_cache_dir(subdir)` platform-standard cache directory (macOS/Linux/Windows), `SQLSEED_CACHE_DIR` environment variable takes highest priority, shared by SnapshotManager and AiConfigRefiner |
| `progress.py` | `create_progress()` three-backend progress bar factory: Null (disabled) / Rich (terminal, with ASCII fallback) / tqdm (Jupyter), auto-selected by runtime environment |
| `sql_safe.py` | SQL injection protection three layers: `validate_table_name()` / `quote_identifier()` / `build_insert_sql()`; double-quote escaping, rejects `; \n \r '` but allows `-` |

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
