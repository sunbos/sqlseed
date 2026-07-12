<!-- Parent: ../AGENTS.md -->
<!-- Last updated: 2026-07-12 -->

# test_utils

## Purpose

Utility module tests. Covers logging configuration, metrics collection, cache path resolution, and progress bar display.

## Key Files

| File | Description |
|------|-------------|
| `test_logger.py` | structlog configuration and `get_logger()` tests |
| `test_metrics.py` | MetricsCollector metrics collection tests |
| `test_paths.py` | Cache path resolution tests (platform-aware, `SQLSEED_CACHE_DIR` override) |
| `test_progress.py` | Progress bar display tests (Null/Rich/tqdm backends) |

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
