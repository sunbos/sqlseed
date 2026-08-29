<!-- Parent: ../AGENTS.md -->
<!-- Last updated: 2026-08-30 -->

# test_utils

## Purpose

Utility module tests. Covers logging configuration, metrics collection, cache path resolution, and progress bar display. 4 files, 99 test functions.

## Key Files

| File | Tests | Description |
|------|------:|-------------|
| `test_progress.py` | 43 | Null/Rich/tqdm backends + env detection |
| `test_logger.py` | 41 | structlog config + `get_logger()` |
| `test_paths.py` | 9 | cache dir (platform-aware, `SQLSEED_CACHE_DIR` override) |
| `test_metrics.py` | 6 | MetricsCollector aggregates |

## For AI Agents

### Working In This Directory

- Verify metric recording, filtering, and aggregate statistics
- Test boundary cases for empty metric sets
- Logger tests must verify structlog auto-configuration on module import
- Path tests must cover macOS/Linux/Windows platform differences and env var override

### Testing Requirements

```bash
pytest tests/test_utils/
```

### Common Patterns

- Directly instantiate `MetricsCollector` for testing
- Use `tmp_path` for cache directory isolation in path tests

## Dependencies

### Internal

- `src/sqlseed/_utils/`

### External

- `pytest>=8.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
