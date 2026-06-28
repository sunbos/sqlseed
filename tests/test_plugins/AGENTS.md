<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-06-21 -->

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

- Test plugin registration, discovery, and unloading
- Verify correct hook call dispatch
- Test entry_points auto-discovery mechanism

### Testing Requirements

```bash
pytest tests/test_plugins/
```

### Common Patterns

- Use `unittest.mock.patch` to mock entry_points

## Dependencies

### Internal

- `src/sqlseed/plugins/`

### External

- `pytest>=8.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
