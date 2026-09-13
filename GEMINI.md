# sqlseed - Project Context

> **Single source of truth: [CLAUDE.md](./CLAUDE.md)**
>
> This file is a pointer for Gemini CLI. All project context, architecture,
> conventions, and coding rules live in `CLAUDE.md` to avoid documentation
> drift. Read `CLAUDE.md` for the authoritative and maintained project guide.
>
> Do not duplicate content here — edit `CLAUDE.md` instead.

## Quick Reference

- **Build & install**: `pip install -e ".[dev,all]"`
- **Run tests**: `pytest`
- **Lint**: `ruff check src/ tests/ plugins/`
- **Type check**: `mypy src/sqlseed/ plugins/`
- **CLI**: `sqlseed fill app.db -t users -n 10000`

For everything else (architecture, module map, conventions, anti-patterns,
plugin docs, release checklist), see [CLAUDE.md](./CLAUDE.md).
