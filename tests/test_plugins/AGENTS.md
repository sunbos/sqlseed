<!-- Parent: ../AGENTS.md -->
<!-- Last updated: 2026-07-12 -->

# test_plugins

## Purpose

Plugin system tests. Covers hook specification definitions and plugin manager lifecycle.

## Key Files

| File | Description |
|------|-------------|
| `test_hookspecs.py` | Hook specification definition tests |
| `test_manager.py` | PluginManager lifecycle tests |

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
