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
   pip install -e ".[dev,all]"
   pip install -e "./plugins/sqlseed-ai"
   pip install -e "./plugins/mcp-server-sqlseed"
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
pytest tests/test_core/             # Core only
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
feat(database): add MySQL support via SQLAlchemyAdapter

- Add pymysql as optional dependency
- Update TypeNormalizer for MySQL types
- Add integration tests for MySQL
```

## Pull Request Process

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feat/your-feature
   ```

2. Make your changes, ensuring:
   - All tests pass: `pytest`
   - Linting passes: `ruff check .`
   - Type checking passes: `mypy src/sqlseed/ plugins/`
   - Documentation is updated

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
- Use fixtures from `tests/conftest.py`
- Integration tests should use `testcontainers` for database tests
- Aim for at least 80% coverage on new code

## Documentation

- Update documentation when adding new features
- README.md and README.zh-CN.md should be kept in sync
- Add entries to CHANGELOG.md following [Keep a Changelog](https://keepachangelog.com/) format

## Questions?

Feel free to open an issue with the `question` label if you have any questions.
