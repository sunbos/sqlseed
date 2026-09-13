# Multi-Database Support Design Document

**Date**: 2026-06-19
**Status**: Design Phase
**Branch**: `feat/multi-db-support` (to be created)
**Goal**: Extend sqlseed from SQLite-only to support PostgreSQL (Phase 1) and more databases

---

## 1. Background and Motivation

### 1.1 Current State

sqlseed currently supports only SQLite. The database adapter layer has two implementations:

- `RawSQLiteAdapter` — based on Python standard library `sqlite3`
- `SQLiteUtilsAdapter` — based on the `sqlite-utils` third-party library

The code is deeply coupled with SQLite-specific syntax (`PRAGMA`, `sqlite_master`, `sqlite_sequence`, `PRAGMA table_info`, etc.) and cannot be directly extended to other databases.

### 1.2 Refactoring Goals

- Phase 1 supports PostgreSQL to validate whether the abstraction design is sufficient
- Maintain zero regression for existing SQLite user experience
- Reserve extension points for future support of MySQL, DuckDB, and other databases

### 1.3 Core Constraints

- **Zero changes to main branch**: All development occurs on the `feat/multi-db-support` branch; merging is only allowed after all tests pass
- **Backward compatibility**: Existing API, CLI, and configuration file formats remain unchanged
- **Progressive refactoring**: Four phases, each independently verifiable

---

## 2. Key Decisions

| Decision Point | Conclusion | Rationale |
|----------------|------------|----------|
| Phase 1 Database | PostgreSQL | Closest to standard SQL, most different from SQLite, fully validates the abstraction |
| Adapter Strategy | SQLAlchemy unified adapter | Shields database differences, reduces duplicate code |
| AI Plugin | Decoupled from database, dialect passed via context | AI consumes abstract data structures like `ColumnInfo`, no need to be aware of the underlying layer |
| MCP Positioning | Focus on generation + pair with general MCP | Complementary to general MCPs like `mcp-server-sql` |
| SQLAlchemy Dependency | Core dependency | Simplifies code path; SQLite dialect uses built-in `sqlite3` with zero extra dependencies |
| Database Driver | Optional plugin | `sqlseed[postgres]`, `sqlseed[mysql]` installed on demand |
| sqlite-utils | Retired | sqlseed uses only 10% of its functionality; SQLAlchemy fully covers it |
| Implementation Path | Progressive refactoring (Option A) | Lowest risk, each phase independently verifiable |

---

## 3. Dependency Model

### 3.1 Installation Methods

```bash
# SQLite out of the box (SQLAlchemy's SQLite dialect uses built-in sqlite3)
pip install sqlseed

# PostgreSQL support
pip install sqlseed[postgres]

# MySQL support (future)
pip install sqlseed[mysql]

# All databases + generators
pip install sqlseed[all]
```

### 3.2 Driver Missing Handling

When a user connects to a database without the driver installed, SQLAlchemy raises `NoSuchModuleError`. sqlseed catches it and provides a friendly message:

```
RuntimeError: PostgreSQL driver not installed.
Install with: pip install sqlseed[postgres]
```

### 3.3 Dependency Changes

| Dependency | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|------------|---------|---------|---------|---------|
| `sqlalchemy>=2.0` | - | core | core | core |
| `psycopg[binary]>=3.0` | - | - | optional[postgres] | optional[postgres] |
| `sqlite-utils` | optional | optional | optional | **removed** |
| `faker` | optional | optional | optional | optional |
| `mimesis` | optional | optional | optional | optional |

---

## 4. Database Layer Architecture

### 4.1 Directory Structure

```
src/sqlseed/database/
├── _protocol.py            # DatabaseAdapter protocol (evolving)
├── _dialect.py             # New: Dialect protocol + dialect implementations
├── _type_normalizer.py     # New: TypeNormalizer type normalization
├── _bulk_optimizer.py      # New: BulkWriteOptimizer protocol + dialect implementations
├── sqlalchemy_adapter.py   # New: SQLAlchemyAdapter
├── raw_sqlite_adapter.py   # Kept in Phase 1-3; in Phase 4 optionally kept as no-SQLAlchemy fallback
├── sqlite_utils_adapter.py # Kept in Phase 1-3; deleted in Phase 4
├── optimizer.py            # Kept; SQLiteBulkOptimizer internally delegates to it
├── _base_adapter.py        # Kept in Phase 1-3; evaluate refactoring in Phase 4
├── _helpers.py             # Kept
├── _compat.py              # Kept in Phase 1-3; deleted in Phase 4 (along with sqlite_utils_adapter retirement)
└── __init__.py             # Updated exports
```

### 4.2 Dialect Protocol

Encapsulates database-specific behavior so upper-layer code does not need to be aware of the underlying dialect.

```python
# _dialect.py
from __future__ import annotations
from typing import Protocol, runtime_checkable
from collections.abc import Callable


@runtime_checkable
class Dialect(Protocol):
    """Database dialect abstraction, encapsulating database-specific behavior"""

    name: str  # "sqlite", "postgresql", "mysql"

    def normalize_type(self, raw_type: str) -> str:
        """Normalize the database raw type name to sqlseed internal type
        SQLite: "TEXT" → "TEXT", "INTEGER" → "INTEGER"
        PG: "character varying(255)" → "VARCHAR(255)"
        """
        ...

    def detect_autoincrement(self, column_info: dict) -> bool:
        """Detect whether a column is auto-incrementing
        SQLite: parse CREATE TABLE to find AUTOINCREMENT
        PG: detect SERIAL / IDENTITY / nextval()
        """
        ...

    def reset_autoincrement(self, execute_fn: Callable[..., object], table_name: str) -> None:
        """Reset the auto-increment counter
        SQLite: DELETE FROM sqlite_sequence
        PG: TRUNCATE ... RESTART IDENTITY / ALTER SEQUENCE
        MySQL: ALTER TABLE ... AUTO_INCREMENT = 1
        """
        ...

    def quote_identifier(self, name: str) -> str:
        """Quote an identifier
        SQLite/PG: "name"
        MySQL: `name`
        """
        ...

    def create_batch_inserter(self, engine: object, table_name: str) -> BatchInserter:
        """Create a batch writer
        SQLite: SQLAlchemy bulk_insert_mappings
        PG: psycopg3 COPY protocol (5-10x faster than INSERT)
        """
        ...


class BatchInserter(Protocol):
    """Batch writer interface"""
    def insert(self, rows: list[dict]) -> int: ...
```

### 4.3 SQLiteDialect Implementation

```python
class SQLiteDialect:
    name = "sqlite"

    def normalize_type(self, raw_type: str) -> str:
        # SQLite types are already in normalized uppercase form
        return raw_type.upper() if raw_type else "TEXT"

    def detect_autoincrement(self, column_info: dict) -> bool:
        # Delegate to existing schema_helpers.detect_autoincrement
        # Parse CREATE TABLE SQL to find AUTOINCREMENT keyword
        ...

    def reset_autoincrement(self, execute_fn, table_name: str) -> None:
        execute_fn("DELETE FROM sqlite_sequence WHERE name = ?", [table_name])

    def quote_identifier(self, name: str) -> str:
        escaped = name.replace('"', '""')
        return f'"{escaped}"'

    def create_batch_inserter(self, engine, table_name: str) -> BatchInserter:
        return SQLAlchemyBatchInserter(engine, table_name)
```

### 4.4 PostgresDialect Implementation

```python
class PostgresDialect:
    name = "postgresql"

    _TYPE_MAP = {
        "serial": "INTEGER",
        "bigserial": "INTEGER",
        "character varying": "VARCHAR",
        "character": "CHAR",
        "timestamp without time zone": "TIMESTAMP",
        "timestamp with time zone": "TIMESTAMPTZ",
        "double precision": "FLOAT",
        "boolean": "BOOLEAN",
        "smallint": "INTEGER",
        "bigint": "INTEGER",
        "real": "FLOAT",
        "bytea": "BLOB",
        "jsonb": "JSON",
        "json": "JSON",
        "uuid": "UUID",
        "text": "TEXT",
        "integer": "INTEGER",
        "numeric": "NUMERIC",
    }

    def normalize_type(self, raw_type: str) -> str:
        # Extract base type and modifiers
        # "character varying(255)" → "VARCHAR(255)"
        # "numeric(10,2)" → "NUMERIC(10,2)"
        ...

    def detect_autoincrement(self, column_info: dict) -> bool:
        # Triple detection:
        # 1. SQLAlchemy's identity attribute (GENERATED ... AS IDENTITY)
        # 2. default value contains nextval (SERIAL pattern)
        # 3. autoincrement flag (SQLAlchemy's inference for integer PKs)
        if column_info.get("identity") is not None:
            return True
        default = column_info.get("default")
        if default and "nextval" in str(default):
            return True
        if column_info.get("autoincrement"):
            return True
        return False

    def reset_autoincrement(self, execute_fn, table_name: str) -> None:
        # PG reset sequence: ALTER SEQUENCE <seq> RESTART WITH 1
        # Need to first look up the sequence name corresponding to the table
        ...

    def quote_identifier(self, name: str) -> str:
        escaped = name.replace('"', '""')
        return f'"{escaped}"'

    def create_batch_inserter(self, engine, table_name: str) -> BatchInserter:
        return PostgresCopyInserter(engine, table_name)
```

### 4.5 TypeNormalizer

Protects the 74 exact match rules in `mapper.py` from becoming invalid.

```python
# _type_normalizer.py
from __future__ import annotations
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedType:
    """Normalized type information"""
    base: str           # "VARCHAR"
    params: tuple       # (255,) or (10, 2)
    raw: str            # original "character varying(255)"

    @property
    def display(self) -> str:
        """Display form: "VARCHAR(255)" or "INTEGER" """
        if self.params:
            return f"{self.base}({','.join(str(p) for p in self.params)})"
        return self.base


_TYPE_PARAMS_RE = re.compile(r"^([^(]+)\s*(?:\(([^)]+)\))?")


class TypeNormalizer:
    """Normalizes type names from different databases so mapper.py rules continue to work"""

    def normalize(self, raw_type: str, dialect_name: str) -> NormalizedType:
        # 1. Extract base type name and parameters
        match = _TYPE_PARAMS_RE.match(raw_type.strip())
        if not match:
            return NormalizedType(base=raw_type.upper(), params=(), raw=raw_type)

        base_raw = match.group(1).strip().lower()
        params_str = match.group(2)

        # 2. Dialect mapping
        base = self._map_base_type(base_raw, dialect_name)

        # 3. Parse parameters
        params = ()
        if params_str:
            params = tuple(int(p.strip()) for p in params_str.split(","))

        return NormalizedType(base=base, params=params, raw=raw_type)

    def _map_base_type(self, base_raw: str, dialect_name: str) -> str:
        if dialect_name == "postgresql":
            return _PG_TYPE_MAP.get(base_raw, base_raw.upper())
        elif dialect_name == "mysql":
            return _MYSQL_TYPE_MAP.get(base_raw, base_raw.upper())
        else:  # sqlite
            return base_raw.upper()


_PG_TYPE_MAP = {
    "serial": "INTEGER",
    "bigserial": "INTEGER",
    "character varying": "VARCHAR",
    "character": "CHAR",
    "timestamp without time zone": "TIMESTAMP",
    "timestamp with time zone": "TIMESTAMPTZ",
    "double precision": "FLOAT",
    "boolean": "BOOLEAN",
    "smallint": "INTEGER",
    "bigint": "INTEGER",
    "real": "FLOAT",
    "bytea": "BLOB",
    "jsonb": "JSON",
    "json": "JSON",
    "uuid": "UUID",
    "text": "TEXT",
    "integer": "INTEGER",
    "numeric": "NUMERIC",
}

_MYSQL_TYPE_MAP = {
    "int": "INTEGER",
    "bigint": "INTEGER",
    "smallint": "INTEGER",
    "tinyint": "INTEGER",
    "varchar": "VARCHAR",
    "char": "CHAR",
    "text": "TEXT",
    "datetime": "DATETIME",
    "timestamp": "TIMESTAMP",
    "double": "FLOAT",
    "float": "FLOAT",
    "boolean": "BOOLEAN",
    "blob": "BLOB",
    "json": "JSON",
}
```

### 4.6 BulkWriteOptimizer Protocol

```python
# _bulk_optimizer.py
from __future__ import annotations
from typing import Protocol


class BulkWriteOptimizer(Protocol):
    """Batch write performance optimizer"""

    def preserve(self) -> None:
        """Save current database configuration"""
        ...

    def optimize(self, expected_rows: int | None = None) -> None:
        """Apply batch write optimizations
        SQLite: PRAGMA synchronous = OFF, journal_mode = MEMORY
        PG: SET synchronous_commit = OFF
        MySQL: SET unique_checks = 0
        """
        ...

    def restore(self) -> None:
        """Restore original configuration"""
        ...


class SQLiteBulkOptimizer:
    """Refactored from existing PragmaOptimizer"""
    # Delegates to optimizer.py's PragmaOptimizer


class PostgresBulkOptimizer:
    """PG batch write optimization"""
    # SET synchronous_commit = OFF
    # Optional: ALTER TABLE ... SET UNLOGGED (when data is reproducible)


class MySQLBulkOptimizer:
    """MySQL batch write optimization"""
    # ALTER TABLE ... DISABLE KEYS
    # SET unique_checks = 0
    # SET foreign_key_checks = 0
```

### 4.7 DatabaseAdapter Protocol Evolution

```python
# _protocol.py — new properties (optional, with default implementations)
@runtime_checkable
class DatabaseAdapter(Protocol):
    # ... existing methods unchanged ...

    @property
    def dialect(self) -> Dialect:
        """Database dialect"""
        ...

    @property
    def bulk_optimizer(self) -> BulkWriteOptimizer | None:
        """Batch write optimizer (optional)"""
        ...
```

### 4.8 SQLAlchemyAdapter

```python
# sqlalchemy_adapter.py
from __future__ import annotations
from typing import Any
from collections.abc import Iterator

from sqlalchemy import create_engine, inspect


class SQLAlchemyAdapter:
    """SQLAlchemy-based unified database adapter"""

    def __init__(self) -> None:
        self._engine = None
        self._inspector = None
        self._dialect = None
        self._optimizer = None
        self._db_url = ""

    def connect(self, db_url: str) -> None:
        """Supports multiple connection methods:
        "sqlite:///path/to/db"           → SQLite
        "postgresql://user:pass@host/db" → PostgreSQL
        "mysql+pymysql://user:pass@host/db" → MySQL
        Also compatible with pure file paths: "/path/to/db.sqlite" → auto-converted to sqlite:/// URL
        """
        # Pure file path auto-converted to SQLite URL
        if "://" not in db_url:
            db_url = f"sqlite:///{db_url}"

        self._db_url = db_url
        self._engine = create_engine(db_url)
        self._inspector = inspect(self._engine)
        self._dialect = self._detect_dialect()
        self._optimizer = self._create_optimizer()

    def _detect_dialect(self) -> Dialect:
        dialect_name = self._engine.dialect.name
        if dialect_name == "sqlite":
            return SQLiteDialect()
        elif dialect_name == "postgresql":
            return PostgresDialect()
        elif dialect_name == "mysql":
            # Not implemented in Phase 3, future extension
            raise NotImplementedError(f"MySQL support not yet implemented")
        raise ValueError(f"Unsupported dialect: {dialect_name}")

    def _create_optimizer(self) -> BulkWriteOptimizer | None:
        if isinstance(self._dialect, SQLiteDialect):
            return SQLiteBulkOptimizer(...)
        elif isinstance(self._dialect, PostgresDialect):
            return PostgresBulkOptimizer(...)
        return None

    def get_table_names(self) -> list[str]:
        return self._inspector.get_table_names()

    def get_column_info(self, table_name: str) -> list[ColumnInfo]:
        columns = self._inspector.get_columns(table_name)
        pks = set(self._inspector.get_pk_constraint(table_name)["constrained_columns"])
        normalizer = TypeNormalizer()

        result = []
        for col in columns:
            raw_type = str(col["type"])
            normalized = normalizer.normalize(raw_type, self._dialect.name)
            is_pk = col["name"] in pks
            is_autoincrement = self._dialect.detect_autoincrement(col)
            result.append(ColumnInfo(
                name=col["name"],
                type=normalized.display,
                nullable=col.get("nullable", True),
                default=col.get("default"),
                is_primary_key=is_pk,
                is_autoincrement=is_autoincrement,
            ))
        return result

    def batch_insert(
        self,
        table_name: str,
        data: Iterator[dict[str, Any]],
        batch_size: int = 5000,
    ) -> int:
        # Use the batch writer provided by Dialect
        inserter = self._dialect.create_batch_inserter(self._engine, table_name)
        return batch_insert_rows(data, batch_size, inserter.insert)

    def clear_table(self, table_name: str) -> None:
        with self._engine.connect() as conn:
            conn.execute(text(f"DELETE FROM {self._dialect.quote_identifier(table_name)}"))
            self._dialect.reset_autoincrement(conn.execute, table_name)
            conn.commit()

    # ... other method implementations ...
```

### 4.9 Orchestrator Dispatch Logic

```python
# orchestrator.py — _create_adapter evolution
def _create_adapter(self) -> DatabaseAdapter:
    # If user passed a URL (postgresql://, mysql://)
    if self._db_url and "://" in self._db_url:
        return SQLAlchemyAdapter()

    # Backward compatibility: pure file path prefers SQLAlchemy SQLite dialect
    if HAS_SQLALCHEMY:
        return SQLAlchemyAdapter()

    # Fallback: use RawSQLiteAdapter when no SQLAlchemy
    return RawSQLiteAdapter()
```

### 4.10 sql_safe.py Refactoring

Keep the safety validation layer; delegate quoting logic to Dialect.

```python
# sql_safe.py — after refactoring
def quote_identifier(name: str, *, dialect: Dialect | None = None) -> str:
    name = _sanitize_identifier(name)  # safety validation unchanged
    if dialect is not None:
        return dialect.quote_identifier(name)
    # Fallback: default to SQL standard double quotes
    escaped = name.replace('"', '""')
    return f'"{escaped}"'


def build_insert_sql(
    table_name: str,
    column_names: list[str],
    *,
    dialect: Dialect | None = None,
) -> str:
    """Build a safe INSERT SQL statement
    SQLite: INSERT INTO "table" ("col1") VALUES (?, ?)
    PG:     INSERT INTO "table" ("col1") VALUES (%s, %s)
    MySQL:  INSERT INTO `table` (`col1`) VALUES (%s, %s)
    """
    safe_table = quote_identifier(table_name, dialect=dialect)
    safe_columns = ", ".join(quote_identifier(col, dialect=dialect) for col in column_names)
    placeholder = "?" if (dialect is None or dialect.name == "sqlite") else "%s"
    placeholders = ", ".join([placeholder] * len(column_names))
    return f"INSERT INTO {safe_table} ({safe_columns}) VALUES ({placeholders})"
```

---

## 5. AI Plugin Refactoring

### 5.1 Principle

The AI plugin only consumes database-agnostic data structures like `ColumnInfo`/`ForeignKeyInfo`, without awareness of whether the underlying layer is SQLite or PG.

### 5.2 Scope of Changes

| File | Change | Reason |
|------|--------|--------|
| `analyzer.py` SYSTEM_PROMPT | `"SQLite table schemas"` → `"database table schemas"` | Remove hardcoding |
| `analyzer.py` Key Rules | `"INTEGER PRIMARY KEY AUTOINCREMENT"` → `"auto-incrementing primary keys"` | Generic description |
| `analyzer.py` GEMMA_TOOLS | `is_autoincrement` description changed to generic | Generic description |
| `analyzer.py` analyze_table_from_ctx | Add `dialect: str = "sqlite"` parameter | Let AI know the target database type |
| `__init__.py` hook | `sqlseed_ai_analyze_table` passes dialect info | Adapt to new signature |

### 5.3 Prompt Refactoring

```python
SYSTEM_PROMPT = """You are an expert database test data engineer.
You analyze database table schemas and recommend data generation configurations for the sqlseed toolkit.

The schema may come from SQLite, PostgreSQL, MySQL, or other databases.
Column types are normalized (e.g., "VARCHAR" for all variable-length string types,
"INTEGER" for all integer types including SERIAL/BIGSERIAL).

## Key Rules
1. Auto-incrementing primary key columns → do NOT include (auto-skip)
2. Columns with DEFAULT values → do NOT include (auto-skip)
3. Nullable columns → do NOT include unless they have semantic meaning
... (other rules unchanged)
"""
```

### 5.4 Schema Context Passes dialect

```python
def analyze_table_from_ctx(
    self,
    *,
    table_name: str,
    columns: list,
    foreign_keys: list,
    indexes: list,
    sample_data: list,
    all_table_names: list,
    dialect: str = "sqlite",  # new
) -> dict:
    # dialect info passed into prompt so AI knows the target database type
    # but AI's output format is unchanged, still ColumnConfig JSON
    ...
```

---

## 6. MCP Server Refactoring

### 6.1 Principle

Focus on data generation; pair with general MCPs.

### 6.2 Scope of Changes

| File | Change | Reason |
|------|--------|--------|
| `server.py` `_validate_db_path` | → `_validate_db_target`, support URL | Multi-database |
| `server.py` all tool functions | `db_path: str` parameter supports URL | Multi-database |
| `server.py` `DataOrchestrator(...)` | Adapt to new signature | Multi-database |

### 6.3 _validate_db_target Refactoring

```python
def _validate_db_target(db_target: str) -> str:
    """Validate database connection target, supporting file paths and URLs"""
    # URL format: postgresql://user:pass@host/db
    if "://" in db_target:
        return db_target  # URL passes through directly, validated later by SQLAlchemy

    # File path: keep existing validation logic
    resolved = Path(db_target).resolve()
    valid_exts = (".db", ".sqlite", ".sqlite3")
    if not str(resolved).endswith(valid_exts):
        raise ValueError(
            f"Invalid database target: {db_target}. "
            "Must be a .db/.sqlite/.sqlite3 file or a database URL "
            "(e.g., postgresql://user:pass@host/db)."
        )
    if not resolved.exists():
        raise ValueError(f"Database file not found: {db_target}")
    return str(resolved)
```

---

## 7. Public API Evolution

### 7.1 Python API

```python
# src/sqlseed/__init__.py

def connect(
    db_path: str | None = None,   # backward compatible: SQLite file path
    *,
    url: str | None = None,       # new: database URL
    **kwargs,
) -> DataOrchestrator:
    """Connect to database, returns DataOrchestrator context manager

    Supports two connection methods:
    - connect("app.db")                              → SQLite file
    - connect(url="postgresql://user:pass@host/db")  → database URL
    """
    target = url or db_path
    if not target:
        raise ValueError("Either db_path or url must be provided")
    return DataOrchestrator(target, **kwargs)


def fill(
    db_path: str | None = None,
    *,
    url: str | None = None,       # new
    table: str,
    count: int,
    **kwargs,
) -> FillResult:
    """Single-table zero-config fill"""
    target = url or db_path
    if not target:
        raise ValueError("Either db_path or url must be provided")
    with DataOrchestrator(target) as orch:
        return orch.fill_table(table_name=table, count=count, **kwargs)
```

### 7.2 CLI

```bash
# Existing usage unchanged
sqlseed fill app.db -t users -n 10000

# New URL support (auto-detected)
sqlseed fill "postgresql://user:pass@localhost/mydb" -t users -n 10000

# Explicit --url parameter
sqlseed fill --url "postgresql://user:pass@localhost/mydb" -t users -n 10000
```

### 7.3 Configuration File

YAML config adds a `url` field, mutually exclusive with `db_path`:

```yaml
# Existing format unchanged
db_path: app.db

# New URL format
url: postgresql://user:pass@localhost/mydb
```

The `GeneratorConfig` Pydantic model adds a `url` field, with `model_validator` ensuring mutual exclusivity with `db_path`.

---

## 8. Testing Strategy

### 8.1 Validation Commands

Each phase must pass the four validation commands before proceeding to the next:

```bash
ruff check . && ruff format --check . && mypy src plugins && pytest
```

### 8.2 Test Layers

| Test Type | Location | Purpose |
|-----------|----------|---------|
| Contract tests | `tests/test_database_contract.py` | Run the same interface tests against all adapters to ensure consistent behavior |
| Dialect tests | `tests/test_dialect.py` | Validate TypeNormalizer, quote_identifier, autoincrement detection |
| Integration tests | `tests/test_postgres_integration.py` | Real PG connection tests, marked `@pytest.mark.postgres` |
| Regression tests | existing `tests/` | Ensure all existing 618 tests pass |

### 8.3 Contract Test Design

```python
# tests/test_database_contract.py
"""Contract tests that all DatabaseAdapter implementations must pass"""

class DatabaseAdapterContract:
    """Subclass and provide fixtures to auto-test all adapters"""

    @pytest.fixture
    @abstractmethod
    def adapter(self) -> DatabaseAdapter: ...

    @pytest.fixture
    @abstractmethod
    def test_table_sql(self) -> str: ...

    def test_get_table_names(self): ...
    def test_get_column_info(self): ...
    def test_get_primary_keys(self): ...
    def test_get_foreign_keys(self): ...
    def test_batch_insert(self): ...
    def test_clear_table(self): ...
    def test_optimize_and_restore(self): ...


class TestRawSQLiteContract(DatabaseAdapterContract):
    @pytest.fixture
    def adapter(self, tmp_db): return RawSQLiteAdapter()


class TestSQLAlchemySQLiteContract(DatabaseAdapterContract):
    @pytest.fixture
    def adapter(self, tmp_db): return SQLAlchemyAdapter()


class TestSQLAlchemyPostgresContract(DatabaseAdapterContract):
    pytestmark = pytest.mark.postgres

    @pytest.fixture
    def adapter(self, pg_db): return SQLAlchemyAdapter()
```

### 8.4 PG Integration Test CI

```yaml
# .github/workflows/test.yml — add PG service
services:
  postgres:
    image: postgres:16
    env:
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
      POSTGRES_DB: sqlseed_test
    ports: ["5432:5432"]

steps:
  - name: Run tests (SQLite only, default)
    run: pytest

  - name: Run PG integration tests
    run: pytest -m postgres
    env:
      SQLSEED_TEST_PG_URL: postgresql://test:test@localhost/sqlseed_test
```

---

## 9. Four-Phase Migration Plan

### Phase 1: Abstract Dialect + BulkWriteOptimizer + TypeNormalizer

**Goal**: Extract interfaces, zero changes to existing code

**New files**:
- `src/sqlseed/database/_dialect.py` — Dialect protocol + SQLiteDialect implementation
- `src/sqlseed/database/_type_normalizer.py` — TypeNormalizer + NormalizedType
- `src/sqlseed/database/_bulk_optimizer.py` — BulkWriteOptimizer protocol + SQLiteBulkOptimizer

**Modified files**:
- `src/sqlseed/database/_protocol.py` — DatabaseAdapter adds `dialect` and `bulk_optimizer` properties (optional, with default implementations)
- `src/sqlseed/database/__init__.py` — Export new classes

**Unchanged files**:
- `raw_sqlite_adapter.py` — zero changes
- `sqlite_utils_adapter.py` — zero changes
- `optimizer.py` — kept; SQLiteBulkOptimizer internally delegates to it

**Validation**: All existing 618 tests pass + new contract test framework

### Phase 2: Introduce SQLAlchemyAdapter

**Goal**: Add SQLAlchemy adapter, coexisting with existing adapters

**New files**:
- `src/sqlseed/database/sqlalchemy_adapter.py` — SQLAlchemyAdapter implementation

**Modified files**:
- `pyproject.toml` — dependencies adds `sqlalchemy>=2.0`
- `src/sqlseed/database/__init__.py` — Export SQLAlchemyAdapter
- `src/sqlseed/core/orchestrator.py` — `_create_adapter()` adds SQLAlchemy path

**New tests**:
- `tests/test_database_contract.py` — SQLAlchemySQLiteContract contract tests

**Validation**: Existing tests pass + SQLAlchemy SQLite dialect passes contract tests

### Phase 3: PostgreSQL Support

**Goal**: Full PostgreSQL support

**New files**:
- `src/sqlseed/database/_dialect.py` — Add PostgresDialect
- `src/sqlseed/database/_bulk_optimizer.py` — Add PostgresBulkOptimizer
- `tests/test_postgres_integration.py` — PG integration tests

**Modified files**:
- `pyproject.toml` — Add `[project.optional-dependencies] postgres = ["psycopg[binary]>=3.0"]`
- `src/sqlseed/core/orchestrator.py` — `_create_adapter()` supports URL dispatch
- `src/sqlseed/__init__.py` — `connect()` / `fill()` supports `url` parameter
- `src/sqlseed/cli/main.py` — CLI supports `--url` parameter
- `src/sqlseed/config/models.py` — GeneratorConfig adds `url` field
- `plugins/sqlseed-ai/src/sqlseed_ai/analyzer.py` — Remove SQLite hardcoding from prompts
- `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/server.py` — `_validate_db_target` supports URL

**Validation**: Existing tests pass + PG integration tests pass

### Phase 4: Cleanup

**Goal**: Retire old adapters and sqlite-utils

**Deleted files**:
- `src/sqlseed/database/sqlite_utils_adapter.py`
- `src/sqlseed/database/_compat.py`

**Modified files**:
- `pyproject.toml` — Remove `sqlite-utils` optional dependency
- `src/sqlseed/database/__init__.py` — Remove old exports
- `src/sqlseed/core/orchestrator.py` — Remove old adapter references

**Evaluate retention**:
- `raw_sqlite_adapter.py` — Evaluate whether to keep as no-SQLAlchemy fallback (depends on community demand)
- `_base_adapter.py` — Evaluate whether to refactor or keep (depends on RawSQLiteAdapter's fate)

**Validation**: Full test suite passes + docs updated in sync

---

## 10. Documentation Sync Rules

According to the project's `CLAUDE.md` Doc Sync Rules, the following docs need to be updated in sync during the corresponding phases:

| Phase | Source Files | Docs to Update |
|-------|--------------|----------------|
| Phase 2 | `_protocol.py`, `sqlalchemy_adapter.py` | README.md, README.zh-CN.md, docs/architecture.md |
| Phase 3 | `__init__.py`, `cli/main.py`, `config/models.py` | README.md, README.zh-CN.md (API table + CLI reference) |
| Phase 3 | `analyzer.py` | README.md, README.zh-CN.md (AI CLI reference) |
| Phase 4 | `pyproject.toml` | README.md (dependency description) |

---

## 11. Risks and Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| SQLAlchemy introduction causes performance regression | SQLite batch writes slower | Phase 2 uses contract tests to compare performance; keep RawSQLiteAdapter if necessary |
| PG autoincrement detection inaccurate | Data generation anomalies | Triple detection (identity + nextval + autoincrement flag) |
| Type normalization omissions | mapper.py rules fail | Complete PG/MySQL type mapping table + unit test coverage |
| Main branch contamination | Stable version compromised | Strict branch isolation; merge only after each phase passes validation |
| Existing test regression | Functionality broken | Run full 618 tests each phase |

---

## 12. Success Criteria

- [ ] Phase 1: All existing 618 tests pass + contract test framework ready
- [ ] Phase 2: SQLAlchemy SQLite dialect passes contract tests + performance no worse than RawSQLiteAdapter
- [ ] Phase 3: PG integration tests pass + `sqlseed fill "postgresql://..." -t users -n 10000` works
- [ ] Phase 4: sqlite-utils retired + full test suite passes + docs synced
- [ ] Throughout: Zero changes to main branch; all development on `feat/multi-db-support` branch
