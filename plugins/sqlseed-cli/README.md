# sqlseed-cli

CLI plugin for [sqlseed](https://github.com/sunbos/sqlseed) — declarative multi-database test data generation toolkit.

This package provides the `sqlseed` console command with subcommands:

- `fill` — fill a table with generated test data
- `preview` — preview generated data without writing to the database
- `inspect` — inspect database schema and column mapping strategies
- `init` — generate a YAML configuration template
- `replay` — replay a previously saved snapshot

## Install

```bash
pip install sqlseed-cli
```

This auto-pulls the `sqlseed` core package. To enable the AI subcommands
(`ai-suggest`, `ai-analyze`, `auto-heal`), also install `sqlseed-ai`:

```bash
pip install sqlseed-ai
```

## Usage

```bash
sqlseed fill app.db -t users -n 1000
sqlseed preview app.db -t users -n 5
sqlseed inspect app.db --table users --show-mapping
sqlseed init generate.yaml --db app.db
sqlseed fill app.db -t users -n 100 --snapshot
sqlseed replay <cache_dir>/snapshots/YYYY-MM-DD_HHMMSS_ffffff_users.yaml
```

Multi-database connections via `--url`:

```bash
sqlseed fill --url "postgresql+psycopg://user:pass@host/db" -t users -n 1000
sqlseed inspect --url "postgresql+psycopg://user:pass@host/db"
```

## Architecture

This is a standalone package (separate `pyproject.toml`, VCS-shared version
via `hatch-vcs` with `root = "../.."`). Per ARCHITECTURE.md Section 3.2:

- Console entry point: `sqlseed = "sqlseed_cli:main"`
- AI subcommand injection: `sqlseed-ai` registers `ai-suggest`, `ai-analyze`,
  and `auto-heal` via the `sqlseed.cli_commands` entry-point group;
  `sqlseed_cli/__init__.py` iterates this group at startup to attach subcommands.

See the root [ARCHITECTURE.md](../../ARCHITECTURE.md) for the full design.
