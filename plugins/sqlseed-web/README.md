# sqlseed Web

A local browser workbench for declarative SQLite and PostgreSQL test data generation.
Connect a database, edit field rules, preview samples, inspect dependencies and review
generation results. The Python core runs offline; AI suggestions are optional.

## Run from this repository

Create and activate a Python 3.10+ virtual environment, then run from the repository root:

```bash
python -m pip install -e . -e ./plugins/sqlseed-web
sqlseed-web
```

Open `http://127.0.0.1:8630`. The built wheel includes the frontend; no Node or npm build
is needed to use the app. For PostgreSQL, also install the core `postgres` extra.

This workbench requires Core 0.2.4 or its development releases (`sqlseed>=0.2.4.dev0`).
Core 0.2.3 does not provide the workbench runtime interfaces. When using an unreleased
checkout, install Core and Web together with the command above.

## Optional components

Open **Settings → Plugins and versions** to see which components are available and which
features depend on them. Base is built in, Faker is installed with core, and Mimesis is
optional. AI is needed only for model-assisted rule suggestions; accepted rules can be
executed offline.

This workbench requires the AI interfaces from the 0.2.4 release line. It rejects
older importable AI packages instead of reporting them as ready. When trying an
unreleased checkout before matching packages are available on the package index,
install the repository's CLI and AI packages into the same development environment.
The page does not fall back to an incompatible older release.

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

See the [workbench guide](https://github.com/sunbos/sqlseed/blob/main/docs/web-workbench.md)
and [support boundaries](https://github.com/sunbos/sqlseed/blob/main/docs/maintainable-release.md).

## Development checks

```bash
pytest plugins/sqlseed-web/tests/
node --test plugins/sqlseed-web/tests/test_*.cjs
```

License: AGPL-3.0-or-later, as specified in the repository's LICENSE.
