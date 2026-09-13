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

This auto-pulls the `sqlseed>=0.2.4.dev0,<0.3` core package; Core 0.2.3 lacks the URL API required by this CLI. To enable the AI subcommands
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

For config-driven generation, set `db_path` or `url` inside the config file:

```bash
sqlseed fill --config generate.yaml --no-ai
```

`--config` cannot be combined with a positional database path or `--url`.
Omitted `--provider`, `--locale`, and `--batch-size` options preserve the
configuration values; explicitly supplied options override them, even when
their values equal the command's defaults. Without `--config`, the defaults
remain `mimesis`, `en_US`, and `5000` respectively.
If any table reports generation errors, the command prints those errors and
exits with status 1. Each result's `count` is the number of rows actually
committed, including rows committed before a later failure.

For direct `fill --transform script.py --snapshot`, the snapshot retains the
transform path and `replay` applies it again. Keep that script available at the
saved path; a snapshot does not embed its contents.

## Architecture

This is a standalone package (separate `pyproject.toml`, VCS-shared version
via `hatch-vcs` with `root = "../.."`). Per ARCHITECTURE.md Section 3.2:

- Console entry point: `sqlseed = "sqlseed_cli:main"`
- AI subcommand injection: `sqlseed-ai` registers `ai-suggest`, `ai-analyze`,
  and `auto-heal` via the `sqlseed.cli_commands` entry-point group;
  `sqlseed_cli/__init__.py` iterates this group at startup to attach subcommands.

See the root [ARCHITECTURE.md](../../ARCHITECTURE.md) for the full design.
