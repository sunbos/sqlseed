# macOS setup

Use these steps in Terminal with zsh or Bash. They cover the Python environment,
Web/CLI/MCP entry points, and source development. sqlseed uses the same Python API
on macOS, Windows and Linux.

## Choose Python and its architecture

Use Python 3.10 or later; Python 3.12 matches the compatibility test environment.
Install a maintained Python from [python.org](https://www.python.org/downloads/macos/)
or your existing package manager. The python.org universal2 installer supports
both Intel and Apple Silicon. Keep Apple's `/usr/bin/python3` unchanged.
See [Python's macOS instructions](https://docs.python.org/3/using/mac.html).

```bash
command -v python3
python3 --version
python3 -c 'import platform, sys; print(sys.executable); print(platform.machine())'
```

Apple Silicon Python should report `arm64`; Intel Python reports `x86_64`.
On Apple Silicon, use a native terminal and interpreter rather than mixing
Rosetta Python with ARM libraries. With several interpreters installed, replace
`python3` below with the desired version, such as `python3.12`, or its absolute
path. A `python` command need not exist before activating a virtual environment.

## Create a fresh environment

Run in your project or a dedicated application directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -c 'import sys; print(sys.executable)'
```

The printed interpreter should be inside this directory's `.venv/bin`.
Virtual environments cannot be copied from Windows or between Python
architectures. When moving a checkout, preserve the old `.venv` by renaming it
to an unused backup name, then create a new one with the commands above. Keep
your databases and configuration files; only the environment needs rebuilding.
Do the same after moving the checkout if installed commands refer to its old path.

## Install and start

For Web and CLI, install the two entry packages in the activated environment:

```bash
python -m pip install sqlseed-web sqlseed-cli
python -m pip check
sqlseed --help
sqlseed-web
```

Open `http://127.0.0.1:8630` and stop the server with Control-C. SQLite uses
Python's built-in driver. Follow the [quick start](guide.md#quick-start) to create
a table and generate data. For the Python API alone, install `sqlseed` instead.
Use the [installation sets](guide.md#installation) for AI, MCP and exact versions.

Without activation, explicitly use `.venv/bin/python`, `.venv/bin/sqlseed`, or
`.venv/bin/sqlseed-web`. From another directory, use the complete path, such as
`/Users/yourname/sqlseed-env/.venv/bin/sqlseed`. Quote paths containing spaces. For desktop MCP clients
that do not inherit Terminal's `PATH`, obtain the environment's executable path:

```bash
python -m pip install mcp-server-sqlseed
python -c 'import sysconfig; from pathlib import Path; print(Path(sysconfig.get_path("scripts")) / "mcp-server-sqlseed")'
```

Use that complete path as the client's `command`, for example
`/Users/yourname/sqlseed-env/.venv/bin/mcp-server-sqlseed`, with an empty `args`
array. Do not put shell activation commands or literal `~` in that field.
The optional AI MCP entry point is `mcp-server-sqlseed-ai`; see the
[MCP guide](guide.md#mcp-server) for configuration.

### Intel Macs and MCP dependencies

MCP pulls in `cryptography` through PyJWT. Starting with cryptography 49, upstream
no longer supports Intel macOS or publishes Intel macOS wheels. Core, CLI and
Web alone do not need this dependency.
[Upstream release note](https://cryptography.io/en/latest/changelog/#v49-0-0).

On Intel, an MCP or complete development installation can need a local
cryptography build. It requires Xcode Command Line Tools, Rust and OpenSSL,
with a toolchain matching the Python architecture. With Homebrew already
installed, prepare the upstream prerequisites:

```bash
xcode-select --install
brew install rust openssl@3
export OPENSSL_DIR="$(brew --prefix openssl@3)"
```

Run the installation again once the tools are ready. Skip `xcode-select --install`
if Command Line Tools are already installed. These tools serve the optional
dependency build, not SQLite or ordinary Core/Web use. Follow the
[cryptography build instructions](https://cryptography.io/en/50.0.1/installation/#building-cryptography-on-macos)
if compilation fails; an older cryptography pin is not the supported workaround.
The repository's hash-locked, narrowly scoped CI build policy is in
[CI dependency maintenance](https://github.com/sunbos/sqlseed/blob/main/.github/DEPENDENCIES.md).

## Develop from source

Clone the repository, enter its root, and create a fresh environment. Supply
all five local packages in one resolution so a candidate plugin cannot pull a
different Core or CLI from PyPI:

```bash
git clone https://github.com/sunbos/sqlseed.git
cd sqlseed
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,all,docs]' -e './plugins/sqlseed-cli' -e './plugins/sqlseed-ai[dev,mcp]' -e './plugins/mcp-server-sqlseed' -e './plugins/sqlseed-web[dev]'
python -m pip check
```

Git and Python are required. Node.js 24 runs the frontend and Pages deployment
regressions. Make is a convenience; the underlying commands are also available
directly. `make dev-install` includes documentation dependencies.

```bash
ruff check src/ tests/ plugins/
ruff format --check src/ tests/ plugins/
mypy src/sqlseed/ plugins/
lint-imports
pytest -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning
node --test plugins/sqlseed-web/tests/test_*.cjs tests/test_deploy_pages.cjs
python scripts/sync_docs.py --check
python -m mkdocs build --strict
make mutmut
```

External PostgreSQL and real LLM tests can skip when services are unavailable;
those skips do not verify the services. CI coverage and its architecture matrix
are defined in [ci.yml](https://github.com/sunbos/sqlseed/blob/main/.github/workflows/ci.yml).
See [contribution instructions](https://github.com/sunbos/sqlseed/blob/main/CONTRIBUTING.md)
for the full review gates.

## PostgreSQL tests

Choose an isolated local PostgreSQL database or a Docker engine. Outside the
development environment, install `python -m pip install 'sqlseed[postgres]'`
for PostgreSQL support.

For an already running local PostgreSQL server, create a database reserved for
tests and set its SQLAlchemy URL. Replace the example credentials and port:

```bash
export PG_TEST_URL='postgresql+psycopg://test_user:test_password@127.0.0.1:5432/sqlseed_test'
pytest tests/integration/test_pg_*.py tests/integration/test_url_e2e.py plugins/sqlseed-web/tests/test_workbench_postgresql_cycles.py -v
```

Tests create and write tables, so the URL must point to the disposable test
database. When `PG_TEST_URL` is set, the fixture uses that server without starting
Docker. With Docker Desktop or another working Docker engine, omit the variable:

```bash
unset PG_TEST_URL
docker info
pytest tests/integration/test_pg_*.py tests/integration/test_url_e2e.py plugins/sqlseed-web/tests/test_workbench_postgresql_cycles.py -v
```

Testcontainers creates and removes its own PostgreSQL container. The Docker CLI
alone is insufficient: the engine must be running and reachable. Real model
acceptance is separate; use the [AI integration guide](gemma4-integration.md).
