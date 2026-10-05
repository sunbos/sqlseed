# Contributing to sqlseed

First off, thank you for considering contributing to sqlseed! This document outlines the process for contributing to the project.

## Development Environment Setup

### Prerequisites

- Python 3.10 or higher
- Git
- Node.js 24 for frontend and Pages deployment tests
- (Optional) Docker for integration tests

For native Python, Intel dependency builds, desktop entry points, and local
PostgreSQL on macOS, follow the [macOS setup guide](docs/macos.md).

### Setup

1. Fork and clone the repository:
   ```bash
   git clone https://github.com/<your-username>/sqlseed.git
   cd sqlseed
   ```

2. Create a virtual environment with your chosen Python 3.10+ interpreter.
   On macOS/Linux:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

   On Windows, using PowerShell:
   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   Recreate virtual environments when moving between operating systems or
   architectures; preserve the old directory under an unused backup name first.

3. Install development dependencies:
   ```bash
   python -m pip install -e ".[dev,all,docs]" -e "./plugins/sqlseed-cli" -e "./plugins/sqlseed-ai[dev]" -e "./plugins/mcp-server-sqlseed" -e "./plugins/sqlseed-web[dev]"
   python -m pip check
   ```

4. Install pre-commit hooks:
   ```bash
   pip install pre-commit
   pre-commit install
   ```

## Code Standards

### Linting and Formatting

We use [ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
ruff check src/ tests/ plugins/
ruff format src/ tests/ plugins/
```

Configuration is in `pyproject.toml` (line length: 120).

### Type Checking

We use [mypy](https://mypy-lang.org/) in strict mode:

```bash
mypy src/sqlseed/ plugins/
```

### Testing

Run tests with [pytest](https://docs.pytest.org/):

```bash
pytest                              # All tests
pytest tests/test_core/             # Core subdirectory tests; excludes root API regressions
pytest --cov=sqlseed                # Core coverage; CI measures all five packages
```

Real AI acceptance requires an installed AI plugin and a running Gemma 4 backend.
Start Ollama with a pulled model, or LM Studio with a loaded model and its server
at `http://localhost:1234/v1`; the default healer model is `google/gemma-4-e2b`
(override with `SQLSEED_TEST_LLM_MODEL`). The shared analyzer/CLI/MCP tests can
also use Google AI Studio with `GOOGLE_API_KEY`. Keep credentials out of the
repository and use only temporary test databases.

```bash
pytest tests/integration/test_ai_real_llm.py --require-llm -v
pytest plugins/sqlseed-ai/tests/test_mcp.py -m integration --require-llm -v
pytest plugins/sqlseed-ai/tests/healer/ -m integration --require-llm -v
```

`--require-llm` makes missing service/model prerequisites fail these selected
tests, while normal offline runs may skip them. Once a service responds, HTTP or
model-list errors, failed inference, and nonzero CLI exits always fail; they
must not be relabeled as skips. A passing protocol test using a fixed local HTTP
response does not certify real model quality.

### Code Style

- **Type hints**: Use `from __future__ import annotations` at the top of every file
- **Logging**: Use structlog via `sqlseed._utils.logger.get_logger(__name__)`
- **SQL safety**: Always use `quote_identifier()` from `_utils/sql_safe.py`
- **Error handling**: Use `RuntimeError`/`ValueError`, never `assert` for runtime validation
- **Docstrings**: English, follow PEP 257

## Commit Convention

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Code style (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding tests
- `chore`: Build process, dependencies, etc.

Example:
```
feat(database): add PostgreSQL support via SQLAlchemyAdapter

- Add psycopg as optional dependency
- Update TypeNormalizer for PostgreSQL types
- Add integration tests for PostgreSQL
```

## Pull Request Process

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feat/your-feature
   ```

2. Make your changes, ensuring:
   - All tests pass: `pytest`
   - Linting and formatting pass: `ruff check src/ tests/ plugins/` and `ruff format --check src/ tests/ plugins/`
   - Type checking passes: `mypy src/sqlseed/ plugins/`
   - Boundaries and docs pass: `lint-imports` and `pytest tests/test_architecture.py tests/test_doc_sync.py`
   - Web frontend regressions pass: `node --test plugins/sqlseed-web/tests/test_*.cjs`
   - The local mutation gate passes: `make mutmut`
   - Documentation is updated; run `python scripts/sync_docs.py --check` and `make docs-build` (strict MkDocs)

3. Commit your changes following the commit convention above.

4. Push to your fork and create a Pull Request:
   - Provide a clear description of the changes
   - Link any related issues
   - Ensure CI passes

5. Wait for review and address feedback.

On pull requests, the `docs` deployment job is intentionally skipped. The `lint`
job still builds the maintained documentation in strict mode; deployment runs
after the required checks succeed on `main`.

### Additional PR review

`.coderabbit.yaml` configures CodeRabbit reviews in Simplified Chinese, using
the repository's architecture and directory instructions. Once the maintainer
installs the [CodeRabbit GitHub App](https://docs.coderabbit.ai/platforms/github-com)
for this repository, it reviews non-draft PRs and subsequent pushes automatically.
The configuration file alone does not install or authorize the App. Limit its
repository access to `sunbos/sqlseed` when enabling it.

CodeRabbit supplements the existing CI, Sonar, and Codecov checks. Review findings
against the current diff and verify fixes with behavioral tests; a clean AI review
does not replace the required checks or real external-service acceptance. It does
not automatically approve or merge PRs under this configuration.

## Branch Strategy

- `main`: Stable, production-ready code
- `feat/*`: Feature branches
- `fix/*`: Bug fix branches

Never commit directly to `main`. Always use a feature branch and create a PR.

## Testing Guidelines

- Write tests for all new features
- Follow the existing test naming convention: `test_<module>.py`
- Use fixtures from the root `conftest.py`
- Use real temporary SQLite databases. PostgreSQL integration tests prefer an isolated
  `PG_TEST_URL`; without it, the shared fixture starts a disposable database with
  `testcontainers`. Never point integration tests at a business database.
- Add behavior regressions for changed paths and satisfy the coverage checks
  reported by Codecov for the current PR. Overall coverage and a fixed local
  percentage do not replace patch coverage; skipped external-service tests are
  not passing evidence.

## Documentation

- Update documentation when adding new features
- README.md and README.zh-CN.md should be kept in sync
- Update both CHANGELOG.md and CHANGELOG.zh-CN.md for releases, following [Keep a Changelog](https://keepachangelog.com/) format
- See [the release guide](docs/releasing.md) for five-package builds and public PyPI acceptance

## Questions?

Feel free to open an issue with the `question` label if you have any questions.
