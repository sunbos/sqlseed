<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-06-21 -->

# test_config

## Purpose

Configuration system tests. Covers model validation, file loading, and snapshot management.

## Key Files

| File | Description |
|------|-------------|
| `test_loader.py` | YAML/JSON config loading tests |
| `test_models.py` | Pydantic model validation tests |
| `test_snapshot.py` | SnapshotManager snapshot management tests |

## For AI Agents

### Working In This Directory

- Model validation must cover source-column/derived-column mutual exclusion constraint
- Loader must cover both YAML and JSON formats
- Must test error messages for invalid config files
- Snapshot tests verify save/load/list_snapshots lifecycle

### Testing Requirements

```bash
pytest tests/test_config/
```

### Common Patterns

- Use `tmp_path` to create test config files
- Multi-DB URL config tests use `url` field (mutually exclusive with `db_path`)

## Dependencies

### Internal

- `src/sqlseed/config/`

### External

- `pytest>=8.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
