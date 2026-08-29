<!-- Parent: ../AGENTS.md -->
<!-- Last updated: 2026-08-30 -->

# test_config

## Purpose

Configuration system tests. Covers model validation, file loading, and snapshot management. 3 files, 39 test functions.

## Key Files

| File | Tests | Description |
|------|------:|-------------|
| `test_models.py` | 17 | Pydantic model validation (source/derived mutual exclusion) |
| `test_loader.py` | 16 | YAML/JSON loading |
| `test_snapshot.py` | 6 | SnapshotManager save/load/list_snapshots |

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
