# API Reference

This page documents the public Python API of `sqlseed`. All functions and classes
below are exported from the top-level `sqlseed` package and are stable across
patch releases.

```python
import sqlseed

print(sqlseed.__version__)
```

---

## Public API

### `fill()`

Fill a single table with generated test data.

```python
sqlseed.fill(
    db_path: str | None = None,
    *,
    url: str | None = None,
    table: str,
    count: int = 1000,
    columns: dict[str, Any] | None = None,
    provider: str = "mimesis",
    locale: str = "en_US",
    seed: int | None = None,
    batch_size: int = 5000,
    clear_before: bool = False,
    optimize_pragma: bool = True,
    enrich: bool = False,
    transform: str | None = None,
    skip_ai: bool = True,
) -> GenerationResult
```

**Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `db_path` | `str \| None` | `None` | SQLite database file path. Mutually exclusive with `url`. |
| `url` | `str \| None` | `None` | Database URL (e.g. `postgresql://user:pass@host/db`). Mutually exclusive with `db_path`. |
| `table` | `str` | — | Target table name. **Required.** |
| `count` | `int` | `1000` | Number of rows to generate. |
| `columns` | `dict[str, Any] \| None` | `None` | Per-column generation config. Keys are column names; values are generator names (`"email"`) or full dicts (`{"type": "integer", "min_value": 18}`). |
| `provider` | `str` | `"mimesis"` | Data provider: `mimesis`, `faker`, or `base`. |
| `locale` | `str` | `"en_US"` | Locale for localized generators (names, addresses, etc.). |
| `seed` | `int \| None` | `None` | Random seed for reproducible generation. |
| `batch_size` | `int` | `5000` | Rows per batch insert. Larger values trade memory for throughput. |
| `clear_before` | `bool` | `False` | Clear the target table before generating. |
| `optimize_pragma` | `bool` | `True` | Apply SQLite PRAGMA optimizations (journal_mode, synchronous, etc.). |
| `enrich` | `bool` | `False` | Infer column distributions from existing data. |
| `transform` | `str \| None` | `None` | Path to a Python transform script applied per row. |
| `skip_ai` | `bool` | `True` | Skip AI-powered schema analysis. |

**Returns**

A [`GenerationResult`](#generationresult) dataclass with table name, row count, elapsed time, and any errors.

**Raises**

- `ValueError` — If neither `db_path` nor `url` is provided, or if both are provided.
- `RuntimeError` — If the target table does not exist or schema inference fails.

**Example**

```python
import sqlseed

# SQLite
result = sqlseed.fill("app.db", table="users", count=10_000)
print(result)
# → GenerationResult(table=users, count=10000, elapsed=0.52s, speed=19230 rows/s)

# PostgreSQL
result = sqlseed.fill(
    url="postgresql+psycopg://user:pass@localhost:5432/mydb",
    table="users",
    count=10_000,
    seed=42,
    clear_before=True,
)

# Fine-grained column control
result = sqlseed.fill(
    "app.db",
    table="users",
    count=50_000,
    columns={
        "email": "email",
        "age": {"type": "integer", "min_value": 18, "max_value": 65},
        "status": {"type": "choice", "choices": ["active", "inactive"]},
    },
    provider="mimesis",
    locale="en_US",
    seed=42,
)
```

---

### `connect()`

Connect to a database and return a `DataOrchestrator` context manager. Use this
when filling multiple tables that share foreign-key relationships.

```python
sqlseed.connect(
    db_path: str | None = None,
    *,
    url: str | None = None,
    provider: str = "mimesis",
    locale: str = "en_US",
    optimize_pragma: bool = True,
) -> DataOrchestrator
```

**Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `db_path` | `str \| None` | `None` | SQLite file path. Mutually exclusive with `url`. |
| `url` | `str \| None` | `None` | Database URL. Mutually exclusive with `db_path`. |
| `provider` | `str` | `"mimesis"` | Data provider name. |
| `locale` | `str` | `"en_US"` | Locale for localized generators. |
| `optimize_pragma` | `bool` | `True` | Apply SQLite PRAGMA optimizations. |

**Returns**

A [`DataOrchestrator`](#dataorchestrator) instance usable as a context manager.

**Raises**

- `ValueError` — If neither `db_path` nor `url` is provided, or if both are provided.

**Example**

```python
import sqlseed

with sqlseed.connect("app.db", provider="mimesis", locale="en_US") as db:
    db.fill("users", count=10_000, seed=42)
    db.fill("orders", count=50_000)  # FK to users.id auto-resolved
    print(db.report())
```

---

### `fill_from_config()`

Load a YAML/JSON config file and fill all declared tables in topological order
(foreign-key dependencies first). Global parameters in the config can be
overridden via keyword arguments.

```python
sqlseed.fill_from_config(
    config_path: str,
    *,
    skip_ai: bool = True,
    clear_before: bool = False,
    count: int | None = None,
    provider: str | None = None,
    seed: int | None = None,
    batch_size: int | None = None,
    locale: str | None = None,
) -> list[GenerationResult]
```

**Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `config_path` | `str` | — | Path to a YAML or JSON config file. **Required.** |
| `skip_ai` | `bool` | `True` | Skip AI schema analysis. |
| `clear_before` | `bool` | `False` | Clear each table before filling (overrides per-table setting when `True`). |
| `count` | `int \| None` | `None` | Override row count for all tables. |
| `provider` | `str \| None` | `None` | Override data provider. |
| `seed` | `int \| None` | `None` | Override random seed for all tables. |
| `batch_size` | `int \| None` | `None` | Override batch size for all tables. |
| `locale` | `str \| None` | `None` | Override locale. |

**Returns**

A list of [`GenerationResult`](#generationresult) instances, one per table, in
topological order.

**Example**

```python
import sqlseed

results = sqlseed.fill_from_config("generate.yaml", clear_before=True, seed=42)
for r in results:
    print(r)
```

---

### `preview()`

Preview generated data without writing to the database. Useful for debugging
column mapping and generator parameters.

```python
sqlseed.preview(
    db_path: str | None = None,
    *,
    url: str | None = None,
    table: str,
    count: int = 5,
    columns: dict[str, Any] | None = None,
    provider: str = "mimesis",
    locale: str = "en_US",
    seed: int | None = None,
    enrich: bool = False,
    transform: str | None = None,
) -> list[dict[str, Any]]
```

**Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `db_path` | `str \| None` | `None` | SQLite file path. Mutually exclusive with `url`. |
| `url` | `str \| None` | `None` | Database URL. Mutually exclusive with `db_path`. |
| `table` | `str` | — | Target table name. **Required.** |
| `count` | `int` | `5` | Number of rows to preview. |
| `columns` | `dict[str, Any] \| None` | `None` | Per-column generation config. |
| `provider` | `str` | `"mimesis"` | Data provider name. |
| `locale` | `str` | `"en_US"` | Locale for localized generators. |
| `seed` | `int \| None` | `None` | Random seed for reproducible preview. |
| `enrich` | `bool` | `False` | Infer distributions from existing data. |
| `transform` | `str \| None` | `None` | Path to a transform script. |

**Returns**

A list of dicts, where each dict maps column names to generated values.

**Raises**

- `ValueError` — If neither `db_path` nor `url` is provided, or if both are provided.

**Example**

```python
import sqlseed

rows = sqlseed.preview("app.db", table="users", count=5, seed=42)
for row in rows:
    print(row)
# → {'id': 1, 'name': 'John Smith', 'email': 'jsmith@example.com', 'age': 32, ...}
```

---

### `load_config()`

Load a YAML or JSON config file into a `GeneratorConfig` model. The format is
detected from the file extension (`.yaml`/`.yml` or `.json`).

```python
from sqlseed import load_config

config = load_config(config_path: str) -> GeneratorConfig
```

**Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `config_path` | `str` | — | Path to a YAML or JSON config file. **Required.** |

**Returns**

A validated [`GeneratorConfig`](#generatorconfig) instance.

**Raises**

- `FileNotFoundError` — If the file does not exist.
- `ValueError` — If the file content fails Pydantic validation.

**Example**

```python
from sqlseed import load_config

config = load_config("generate.yaml")
print(config.db_path, config.provider, len(config.tables))
```

---

## Configuration Models

All configuration models are Pydantic `BaseModel` subclasses exported from
`sqlseed.config.models` and re-exported from the top-level `sqlseed` package.

### `GeneratorConfig`

Global generation configuration. The connection target is specified via
`db_path` (SQLite file path) **or** `url` (database URL); the two are mutually
exclusive and at least one must be provided.

```python
class GeneratorConfig(BaseModel):
    db_path: str | None = None
    url: str | None = None
    provider: ProviderType = ProviderType.MIMESIS
    locale: str = "en_US"
    tables: list[TableConfig] = []
    associations: list[ColumnAssociation] = []
    optimize_pragma: bool = True
    snapshot_dir: str | None = None
```

**Properties**

| Property | Type | Description |
|----------|------|-------------|
| `connection_target` | `str` | Returns `url` if set, else `db_path`. Raises `RuntimeError` if neither is configured. |

**Validation**

- `db_path` and `url` are mutually exclusive. Providing both raises `ValueError`.
- At least one of `db_path` or `url` must be provided. Providing neither raises `ValueError`.

---

### `TableConfig`

Single-table generation configuration.

```python
class TableConfig(BaseModel):
    name: str
    count: int = 1000           # must be > 0
    batch_size: int = 5000      # must be > 0
    columns: list[ColumnConfig] = []
    clear_before: bool = False
    seed: int | None = None
    transform: str | None = None
    enrich: bool = False
```

---

### `ColumnConfig`

Column configuration. Supports two mutually-exclusive modes:

- **Source-column mode**: specify `generator` + `params` to generate values.
- **Derived-column mode**: specify `derive_from` + `expression` to compute
  values from another column in the same row.

```python
class ColumnConfig(BaseModel):
    name: str

    # Source-column mode
    generator: str | None = None
    provider: ProviderType | None = None
    params: dict[str, Any] = {}
    null_ratio: float = 0.0     # 0.0–1.0

    # Derived-column mode
    derive_from: str | None = None
    expression: str | None = None

    # Constraints
    constraints: ColumnConstraintsConfig | None = None

    # Native method overrides (from AI suggestions)
    faker_method: str | None = None
    mimesis_method: str | None = None
    native_params: dict[str, Any] = {}
```

**Validation**

- `generator` and `derive_from` cannot be used together.
- `derive_from` requires `expression`.

**Dict shorthand**

When constructing from a dict, unknown keys are automatically merged into
`params`, and `type` is treated as an alias for `generator`:

```python
ColumnConfig(name="age", type="integer", min_value=18, max_value=65)
# Equivalent to:
ColumnConfig(name="age", generator="integer", params={"min_value": 18, "max_value": 65})
```

---

### `ColumnConstraintsConfig`

Column constraint configuration. Used by the `ConstraintSolver` for unique
backtracking and value-range enforcement.

```python
class ColumnConstraintsConfig(BaseModel):
    unique: bool = False
    min_value: int | float | None = None
    max_value: int | float | None = None
    regex: str | None = None
    max_retries: int = 100      # must be >= 0
```

---

### `ColumnAssociation`

Cross-table column association declaration. Used for implicit associations
(same-name column references across tables) when no foreign-key constraint
exists.

```python
class ColumnAssociation(BaseModel):
    column_name: str
    source_table: str
    source_column: str | None = None    # defaults to column_name
    target_tables: list[str] = []
    strategy: Literal["shared_pool", "random"] = "shared_pool"
```

---

### `ProviderType`

Enum of supported data provider types.

```python
class ProviderType(str, Enum):
    BASE = "base"       # type-routing only, no real data
    FAKER = "faker"     # Faker engine (required dep)
    MIMESIS = "mimesis" # Mimesis engine (optional, high-performance)
    CUSTOM = "custom"   # user-registered provider
```

---

## Result Types

### `GenerationResult`

Dataclass returned by `fill()` and `fill_from_config()`. Encapsulates
statistics after executing a data generation task.

```python
@dataclass
class GenerationResult:
    table_name: str
    count: int
    elapsed: float
    rows_per_second: float = 0.0     # auto-computed in __post_init__
    batch_count: int = 0
    errors: list[str] = []
```

**Example**

```python
result = sqlseed.fill("app.db", table="users", count=1000)
print(result.table_name)      # "users"
print(result.count)           # 1000
print(result.elapsed)         # 0.52 (seconds)
print(result.rows_per_second) # 19230.0
print(result.errors)          # []
print(str(result))
# → GenerationResult(table=users, count=1000, elapsed=0.52s, speed=19230.00 rows/s)
```

---

## `DataOrchestrator`

The main orchestration engine. Returned by `connect()` and used as a context
manager. Most users will interact with it through `connect()`, but it can also
be instantiated directly.

```python
from sqlseed import DataOrchestrator

with DataOrchestrator(
    db_path="app.db",            # or url="postgresql://..."
    provider_name="mimesis",
    locale="en_US",
    optimize_pragma=True,
) as orch:
    orch.fill_table(table_name="users", count=1000, seed=42)
```

**Key methods**

| Method | Description |
|--------|-------------|
| `fill_table(...)` | Fill a single table. |
| `preview_table(...)` | Preview rows without writing. |
| `get_topological_table_order(names)` | Return table names in FK-dependency order. |
| `get_column_mapping(table)` | Return resolved `GeneratorSpec` per column. |
| `get_column_info(table)` | Return `ColumnInfo` list. |
| `get_foreign_keys(table)` | Return `ForeignKeyInfo` list. |
| `get_row_count(table)` | Return current row count. |
| `report()` | Return a human-readable summary of all fills in this session. |

`DataOrchestrator` also exposes a `from_config(config)` classmethod for
constructing an instance from a `GeneratorConfig`.

---

## Database Adapter Protocol

### `DatabaseAdapter`

A `runtime_checkable` `Protocol` defining the contract for all database
adapters. Implementations provide schema introspection, batch insertion, and
transaction management.

```python
from sqlseed.database import DatabaseAdapter
```

**Protocol methods**

| Method | Signature | Description |
|--------|-----------|-------------|
| `connect` | `(db_path: str) -> None` | Connect to the database. |
| `close` | `() -> None` | Close the connection. |
| `get_table_names` | `() -> list[str]` | List all user tables. |
| `get_column_info` | `(table_name: str) -> list[ColumnInfo]` | Column metadata. |
| `get_primary_keys` | `(table_name: str) -> list[str]` | Primary key column names. |
| `get_foreign_keys` | `(table_name: str) -> list[ForeignKeyInfo]` | Foreign key metadata. |
| `get_row_count` | `(table_name: str) -> int` | Current row count. |
| `get_column_values` | `(table_name, column_name, limit=1000) -> list[Any]` | Sample column values. |
| `get_index_info` | `(table_name: str) -> list[IndexInfo]` | Index metadata. |
| `get_sample_rows` | `(table_name, limit=5) -> list[dict]` | Sample rows. |
| `batch_insert` | `(table_name, data, batch_size=5000) -> int` | Bulk insert from an iterator. |
| `clear_table` | `(table_name: str) -> None` | Delete all rows. |
| `optimize_for_bulk_write` | `(expected_rows: int \| None = None) -> None` | Apply write optimizations. |
| `restore_settings` | `() -> None` | Restore default settings. |
| `execute` | `(sql, params=()) -> Any` | Execute raw SQL. |
| `__enter__` / `__exit__` | — | Context manager support. |

**Supporting dataclasses**

```python
@dataclass(frozen=True)
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    default: Any
    is_primary_key: bool
    is_autoincrement: bool

@dataclass(frozen=True)
class ForeignKeyInfo:
    column: str
    ref_table: str
    ref_column: str

@dataclass(frozen=True)
class IndexInfo:
    name: str
    table: str
    columns: tuple[str, ...]
    unique: bool
```

---

### `SQLAlchemyAdapter`

The **required** adapter for production use. Supports SQLite, PostgreSQL, and
MySQL via SQLAlchemy. Auto-detects the dialect from the connection URL.

```python
from sqlseed.database import SQLAlchemyAdapter
```

**Connection forms**

| URL | Database |
|-----|----------|
| `sqlite:///path/to/db` | SQLite |
| `postgresql+psycopg://user:pass@host/db` | PostgreSQL (requires `sqlseed[postgres]`) |
| `mysql+mysqldb://user:pass@host/db` | MySQL (requires `sqlseed[mysql]`) |
| `/path/to/db.sqlite` | SQLite (auto-converted to `sqlite:///` URL) |

**Dialect attributes**

`SQLAlchemyAdapter` exposes two optional attributes that other adapters may
not implement:

- `dialect` — A `Dialect` instance (`SQLiteDialect`, `PostgresDialect`, etc.)
  providing dialect-specific metadata queries.
- `bulk_optimizer` — A `BulkWriteOptimizer` instance for dialect-specific
  bulk-write strategies.

Upper-layer code checks support via `hasattr(adapter, "dialect")`.

---

### `RawSQLiteAdapter`

A **test-only** adapter based on Python's built-in `sqlite3` module. Uses no
third-party dependencies. Suitable for zero-dependency test scenarios.

```python
from sqlseed.database import RawSQLiteAdapter
```

!!! warning "Not for production"

    `RawSQLiteAdapter` does not implement the `dialect` or `bulk_optimizer`
    attributes and only supports SQLite. For production use, prefer
    `SQLAlchemyAdapter` to get multi-dialect support and bulk-write
    optimization.

**Example**

```python
from sqlseed.database import RawSQLiteAdapter

adapter = RawSQLiteAdapter()
adapter.connect("test.db")
try:
    tables = adapter.get_table_names()
    print(tables)
finally:
    adapter.close()
```

---

## Module Exports

The top-level `sqlseed` package exports:

```python
__all__ = [
    "ColumnConfig",
    "DataOrchestrator",
    "GenerationResult",
    "GeneratorConfig",
    "ProviderType",
    "TableConfig",
    "__version__",
    "connect",
    "fill",
    "fill_from_config",
    "load_config",
    "preview",
]
```

The `sqlseed.database` subpackage additionally exports:

```python
__all__ = [
    "BulkWriteOptimizer",
    "ColumnInfo",
    "DatabaseAdapter",
    "Dialect",
    "ForeignKeyInfo",
    "IndexInfo",
    "NormalizedType",
    "PostgresBulkOptimizer",
    "PostgresDialect",
    "PragmaOptimizer",
    "PragmaProfile",
    "RawSQLiteAdapter",
    "SQLAlchemyAdapter",
    "SQLiteBulkOptimizer",
    "SQLiteDialect",
    "TypeNormalizer",
]
```
