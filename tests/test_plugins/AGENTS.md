<!-- Parent: ../AGENTS.md -->
<!-- Last updated: 2026-08-30 -->

# test_plugins

## Purpose

Plugin system tests. Covers hook specification definitions and plugin manager lifecycle. 2 files, 21 test functions.

## Key Files

| File | Tests | Description |
|------|------:|-------------|
| `test_hookspecs.py` | 15 | 12 hook specs (signatures, firstresult markers) |
| `test_manager.py` | 6 | PluginManager lifecycle |

## For AI Agents

### Working In This Directory

- Test plugin registration and unloading
- Verify correct hook call dispatch

### Testing Requirements

```bash
pytest tests/test_plugins/
```

### Common Patterns

- Use real `PluginManager` instances with inline dummy plugin classes (no mocking)

## Dependencies

### Internal

- `src/sqlseed/plugins/`

### External

- `pytest>=8.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
