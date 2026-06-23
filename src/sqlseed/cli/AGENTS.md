<!-- Parent: ../AGENTS.md -->

# cli

**Generated:** 2026-06-21

## Purpose

Click-based command-line tool. Provides subcommands such as fill, preview, inspect, init, replay, and ai-suggest.

## Key Files

| File | Description |
|------|-------------|
| `main.py` | CLI entry point; defines the `cli` group and core subcommands (fill, preview, inspect, init, replay) |
| `ai_commands.py` | AI-related subcommand (ai-suggest); imported by main.py at startup |
| `__init__.py` | Exports the `cli` group |

## For AI Agents

### Working In This Directory

- New subcommands must be registered with the `cli` group.
- AI features (sqlseed-ai) are gated by the `HAS_AI_PLUGIN` flag and silently degrade on ImportError; a missing sqlseed-ai package must not crash the CLI.
- User-facing output uses click.echo / rich; internal logging uses structlog.
- The CLI layer should stay thin; parameter validation and generation logic belong to the library layer.
- Log level is controlled via the `SQLSEED_LOG_LEVEL` environment variable.

### Testing Requirements

```bash
pytest tests/test_cli.py tests/test_ai_plugin.py
```

### Common Patterns

- Command structure: `cli` (group) -> `fill` / `preview` / `init` / `replay` subcommands (main.py) + `ai-suggest` subcommand (ai_commands.py).
- Output is beautified with the rich library (progress bars, tables, highlighting).
- AI feature degradation pattern: `try: from sqlseed_ai import ... except ImportError: HAS_AI_PLUGIN = False`.
- `--url` multi-database support (mutually exclusive with db_path): the fill/preview/inspect commands all accept `--url` as an alternative to the positional db_path argument.
- `_StreamingProgressDisplay` streaming progress display: a Rich Live display showing phase/token/preview of the LLM streaming output.
- Timeout mechanism: handled uniformly by the LLM client layer (httpx); the CLI layer does not use signals (SIGALRM was removed for cross-platform consistency).

## Dependencies

### Internal

- `core` (DataOrchestrator)
- `config` (load_config, GeneratorConfig)
- `database` (connect adapter)
- `plugins` (PluginManager)
- `_utils` (logger, progress, sql_safe, etc.)

### External

- `click>=8.0` — CLI framework
- `rich>=13.0` — beautified output

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
