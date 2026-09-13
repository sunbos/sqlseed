# sqlseed-cli

Command-line interface for [sqlseed](https://sunbos.github.io/sqlseed/): generate
SQLite and PostgreSQL test data, preview samples, inspect schema, and save or replay
configuration. This package provides the `sqlseed` command.

## Installation

For the 0.2.4 release, use a Python 3.10+ virtual environment:

```bash
python -m pip install "sqlseed-cli==0.2.4"
```

Core 0.2.3 does not provide the URL API required by this CLI.
For development, install Core and the required local plugins together from the
repository root:

```bash
python -m pip install -e . -e ./plugins/sqlseed-cli
```

For AI commands in a source checkout, install all three local packages together:

```bash
python -m pip install -e . -e ./plugins/sqlseed-cli -e ./plugins/sqlseed-ai
```

Installing only `sqlseed` provides the Python API. Install `sqlseed-cli` or the Core
`cli` extra to get the console command. Faker is included with Core; Mimesis is
optional. The examples below select the installed Faker provider explicitly.

## Usage

Create your tables first, then run:

```bash
sqlseed fill app.db -t users -n 1000 --provider faker --no-ai
sqlseed preview app.db -t users -n 5 --provider faker
sqlseed inspect app.db --table users --show-mapping
sqlseed init generate.yaml --db app.db
sqlseed fill app.db -t users -n 100 --provider faker --no-ai --snapshot
sqlseed replay <cache_dir>/snapshots/YYYY-MM-DD_HHMMSS_ffffff_users.yaml
```

| Command | Purpose |
|---|---|
| `fill` | Generate and write data into existing tables |
| `preview` | Generate samples without writing them |
| `inspect` | Show schema and column mapping |
| `init` | Write a YAML configuration template |
| `replay` | Run a saved configuration snapshot |

For PostgreSQL, install the Core `postgres` extra and use `--url`:

```bash
python -m pip install "sqlseed[postgres]==0.2.4" "sqlseed-cli==0.2.4"
sqlseed fill --url "postgresql+psycopg://user:pass@host/db" -t users -n 1000 --provider faker --no-ai
sqlseed inspect --url "postgresql+psycopg://user:pass@host/db"
```

For configuration-driven generation, put exactly one of `db_path` or `url` in the YAML.
Set `provider: faker` in a generated template, or install the optional Mimesis provider
if the template uses `provider: mimesis`:

```bash
sqlseed fill --config generate.yaml --no-ai
```

`--config` cannot be combined with a positional database path or `--url`. Omitted
`--provider`, `--locale`, and `--batch-size` preserve the YAML values. Explicit options
override those values, including options equal to the command defaults. Without
`--config`, the defaults are `mimesis`, `en_US`, and `5000`.

If any table reports generation errors, the command prints those errors and exits
with status 1. `count` reports rows actually committed; a later batch failure can
leave earlier commits. A snapshot retains a supplied transform script path and replay
runs that script again; the script itself is not embedded in the snapshot.

The optional AI plugin registers `ai-suggest`, `ai-analyze`, and `auto-heal` through
`sqlseed.cli_commands`. CLI does not require AI for its five base commands.

## Requirements

- Python `>=3.10`
- `sqlseed>=0.2.4.dev0,<0.3`
- `click>=8.0`
- `rich>=13.0`

See the [user guide](https://sunbos.github.io/sqlseed/guide/),
[migration guide](https://sunbos.github.io/sqlseed/migration/), and
[package source](https://github.com/sunbos/sqlseed/tree/main/plugins/sqlseed-cli).

License: [AGPL-3.0-or-later](https://github.com/sunbos/sqlseed/blob/main/LICENSE).
The distribution includes the full LICENSE text.
