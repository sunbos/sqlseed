# CLAUDE.md — Claude-specific Instructions for sqlseed

This file provides instructions specifically for Claude (Anthropic) when working on the sqlseed codebase. It supplements the general instructions in `AGENTS.md`.

## Project Context

sqlseed is a Python 3.10+ library using `src` layout (`src/sqlseed/`). The architecture design document is at `implementation_plan.md` in the project root — always consult it for design decisions and interface contracts.

## How to Work on This Project

### Before Making Changes

1. Read `implementation_plan.md` for architecture context
2. Read `AGENTS.md` for general conventions
3. Check existing tests in `tests/` to understand testing patterns
4. Run `pytest` to verify baseline before changes

### When Adding Features

1. Follow the Protocol-based design pattern. New providers/adapters must satisfy existing Protocols.
2. All public functions need keyword-only arguments (use `*` separator).
3. Use Pydantic BaseModel for any new configuration structures.
4. Register new components via the existing Registry/Plugin patterns.

### When Fixing Bugs

1. Write a failing test first
2. Fix the bug
3. Verify all 286+ tests pass with `pytest`

## Technical Specifics

### Module Dependencies (Layered Architecture)

```
cli/ → core/ → generators/
                database/
                plugins/
                config/

_utils/ → (no internal dependencies, used by all layers)
```

### Testing Patterns

- **Fixtures**: Common fixtures in `tests/conftest.py` (temp DB paths, sample tables)
- **Adapters**: Tested with real SQLite databases (`:memory:` and tmp files)
- **CLI**: Use `click.testing.CliRunner` — never subprocess
- **Providers**: Test each generate_* method independently
- **Plugins**: Test hook registration and invocation via `PluginManager`

### Key Implementation Details

- `DataOrchestrator.fill()` is the primary alias (matches design doc). `fill_table()` is the original implementation.
- `transform_batch` hooks return `list[result]` (non-firstresult). The orchestrator chains them via `_apply_batch_transforms()`.
- `DataStream` uses its own `random.Random(seed)` instance for null_ratio/choice operations, separate from the provider's RNG.
- `PragmaOptimizer.restore()` validates PRAGMA values with regex before applying them (security measure).
- `_is_autoincrement` detection is centralized in `_utils/schema_helpers.py`.

### Style Guide

```python
# ✅ Good
from __future__ import annotations
from typing import Any

def some_function(*, required_param: str, optional: int = 10) -> list[str]:
    ...

# ❌ Bad
from typing import Union, List, Optional

def some_function(required_param, optional=10):
    ...
```

### Imports

```python
# ✅ Preferred: TYPE_CHECKING guard for type-only imports
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlseed.database._protocol import ColumnInfo

# ✅ Preferred: Lazy imports for optional dependencies
def method(self):
    import sqlite_utils  # imported here, not at module top
```

## File Templates

### New Provider Template

```python
from __future__ import annotations
from typing import Any

class NewProvider:
    def __init__(self) -> None:
        self._locale: str = "en_US"

    @property
    def name(self) -> str:
        return "new_provider"

    def set_locale(self, locale: str) -> None:
        self._locale = locale

    def set_seed(self, seed: int) -> None:
        ...

    # Implement all methods from DataProvider Protocol
    # See: src/sqlseed/generators/_protocol.py
```

### New Test Template

```python
from __future__ import annotations
import pytest

class TestNewFeature:
    def test_basic_case(self, tmp_path):
        ...

    def test_edge_case(self):
        ...

    def test_error_case(self):
        with pytest.raises(ValueError, match="expected message"):
            ...
```

## Common Pitfalls

1. **Seed handling**: Don't set provider seed in orchestrator — `DataStream.__init__` handles it
2. **Hook returns**: `pluggy` returns `list[result]` for non-firstresult hooks, not a single value
3. **sqlite-utils API**: `table.columns_dict` returns `{name: type}`, the type may be a Python type class, not a string
4. **Mimesis locale**: Uses short codes ("en", "zh") not Faker-style ("en_US", "zh_CN") — see `MimesisProvider.set_locale()` mapping
5. **Memory**: Never collect all rows before writing — use `DataStream.generate()` which yields batches

## Useful Commands

```bash
# Run specific test file
pytest tests/test_orchestrator.py -v

# Run tests matching a pattern
pytest -k "test_fill" -v

# Run with full output
pytest --tb=long --no-header -v

# Check coverage for a specific module
pytest --cov=sqlseed.core.orchestrator --cov-report=term-missing

# Lint and auto-fix
ruff check --fix src/ tests/
```
