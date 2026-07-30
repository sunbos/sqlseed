# sqlseed_cli

**Last updated:** 2026-07-12

## Purpose

Click-based command-line tool. Provides subcommands such as fill, preview, inspect, init, replay.
AI-related subcommands (ai-suggest, ai-analyze, auto-heal, registered by sqlseed-ai's
`ai_commands.register()`) are discovered via the `sqlseed.cli_commands`
entry-point group and registered by `__init__.py` at startup.

## Key Files

| File | Description |
|------|-------------|
| `main.py` | CLI entry point; defines the `cli` group and core subcommands (fill, preview, inspect, init, replay) |
| `_utils.py` | Shared CLI utility functions (e.g. `sanitize_table_config()` for stripping leading dots/colons from table and column names) |
| `__init__.py` | Exports `cli` and `main`; discovers and registers plugin subcommands via the `sqlseed.cli_commands` entry-point group |

## For AI Agents

### Working In This Directory

- New core subcommands must be registered with the `cli` group in `main.py`.
- Third-party subcommands (e.g. ai-suggest, ai-analyze, auto-heal from
  sqlseed-ai) are registered via the `sqlseed.cli_commands` entry-point
  group, NOT by direct import.
  This decouples sqlseed-cli from any specific plugin package.
- User-facing output uses click.echo / rich; internal logging uses structlog
  (via `sqlseed._utils.logger`).
- The CLI layer should stay thin; parameter validation and generation logic
  belong to the library layer (`sqlseed.core`).
- Log level is controlled via the `SQLSEED_LOG_LEVEL` environment variable.

### Testing Requirements

```bash
pytest plugins/sqlseed-cli/tests/
```

### Common Patterns

- Command structure: `cli` (group) -> `fill` / `preview` / `inspect` / `init` / `replay`
  subcommands (main.py). Plugin subcommands (e.g. `ai-suggest`, `ai-analyze`,
  `auto-heal`) are attached via entry-points.
- Output is beautified with the rich library (progress bars, tables, highlighting).
- `--url` multi-database support (mutually exclusive with db_path): the
  fill/preview/inspect commands all accept `--url` as an alternative to the
  positional db_path argument.

## Dependencies

### Internal

- `sqlseed` (core: DataOrchestrator, config, _utils.logger)
- This package does NOT depend on `sqlseed-ai` at import time; AI subcommands
  are discovered via entry-points.

### External

- `click>=8.0` — CLI framework
- `rich>=13.0` — beautified output
