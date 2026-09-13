# Contributing to sqlseed

First off, thank you for considering contributing to sqlseed! This document outlines the process for contributing to the project.

## Development Environment Setup

### Prerequisites

- Python 3.10 or higher
- Git
- (Optional) Docker for integration tests

### Setup

1. Fork and clone the repository:
   ```bash
   git clone https://github.com/<your-username>/sqlseed.git
   cd sqlseed
   ```

2. Create a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/macOS
   # or
   .venv\Scripts\activate  # Windows
   ```

3. Install development dependencies:
   ```bash
   python -m pip install -e ".[dev,all]" -e "./plugins/sqlseed-cli" -e "./plugins/sqlseed-ai[dev]" -e "./plugins/mcp-server-sqlseed" -e "./plugins/sqlseed-web[dev]"
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
pytest --cov=sqlseed                # With coverage
```

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
   - Documentation is updated; run `python scripts/sync_docs.py --check`

3. Commit your changes following the commit convention above.

4. Push to your fork and create a Pull Request:
   - Provide a clear description of the changes
   - Link any related issues
   - Ensure CI passes

5. Wait for review and address feedback.

## Branch Strategy

- `main`: Stable, production-ready code
- `feat/*`: Feature branches
- `fix/*`: Bug fix branches

Never commit directly to `main`. Always use a feature branch and create a PR.

## Testing Guidelines

- Write tests for all new features
- Follow the existing test naming convention: `test_<module>.py`
- Use fixtures from the root `conftest.py`
- Integration tests should use `testcontainers` for database tests
- Aim for at least 80% coverage on new code

## Documentation

- Update documentation when adding new features
- README.md and README.zh-CN.md should be kept in sync
- Update both CHANGELOG.md and CHANGELOG.zh-CN.md for releases, following [Keep a Changelog](https://keepachangelog.com/) format
- See [the release guide](docs/releasing.md) for five-package builds and public PyPI acceptance

## Questions?

Feel free to open an issue with the `question` label if you have any questions.
