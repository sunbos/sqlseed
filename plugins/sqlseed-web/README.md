# sqlseed Web

A local browser workbench for declarative SQLite and PostgreSQL test data generation.
Connect a database, edit field rules, preview samples, inspect dependencies and review
generation results. The Python core runs offline; AI suggestions are optional.

## Installation

For the 0.2.4 release, create and activate a Python 3.10+ virtual environment:

```bash
python -m pip install "sqlseed==0.2.4" "sqlseed-web==0.2.4"
sqlseed-web
```

Open `http://127.0.0.1:8630`. The wheel includes the frontend; no Node or npm build
is needed to use the app. For PostgreSQL, also install `"sqlseed[postgres]==0.2.4"`.
Core 0.2.3 does not provide the required workbench runtime interfaces.

For development, install local Core and Web together from the repository root:

```bash
python -m pip install -e . -e ./plugins/sqlseed-web
```

## Optional components

Open **Settings → Plugins and versions** to see which components are available and which
features depend on them. Base is built in, Faker is installed with core, and Mimesis is
optional. AI is needed only for model-assisted rule suggestions; accepted rules can be
executed offline.

This workbench requires the AI interfaces from the 0.2.4 release line. It rejects
older importable AI packages instead of reporting them as ready. For a source checkout,
install local Core, CLI, AI, and Web together in the same resolution:

```bash
python -m pip install -e . -e ./plugins/sqlseed-cli -e ./plugins/sqlseed-ai -e ./plugins/sqlseed-web
```

For the 0.2.4 release, `python -m pip install "sqlseed-web[ai]==0.2.4"` installs
the optional AI component. The page does not fall back to an incompatible older release.

On supported writable macOS/Linux virtual environments, the default launcher manages
optional packages through the page and restores the service automatically. Windows,
externally hosted apps and read-only/system environments can use the workbench but do not
offer in-page package changes. Missing components produce an explanation and recovery
entry point; the app preserves the configuration instead of silently changing its engine.

## Data and deployment boundaries

Preview does not write generated rows. Generation requires an explicit confirmation;
batch failures can leave earlier committed data, so read the run result before retrying.
Use a test database or a disposable copy for demonstrations.

The service is designed for one trusted local user and has no multi-user authentication.
It binds to loopback by default. Do not expose it directly to an untrusted network.
Same-origin request checks do not replace authentication or database permissions.

See the [workbench guide](https://sunbos.github.io/sqlseed/web-workbench/)
and [support boundaries](https://sunbos.github.io/sqlseed/maintainable-release/).

## Requirements

- Python `>=3.10`
- `sqlseed>=0.2.4.dev0,<0.3`
- `fastapi>=0.110`
- `uvicorn>=0.29`
- `pyyaml>=6.0`
- `packaging>=23.2`
- Optional `ai` extra: `sqlseed-ai>=0.2.4.dev0,<0.3`

## Development checks

```bash
pytest plugins/sqlseed-web/tests/
node --test plugins/sqlseed-web/tests/test_*.cjs
```

License: [AGPL-3.0-or-later](https://github.com/sunbos/sqlseed/blob/main/LICENSE).
The distribution includes the full LICENSE text.
