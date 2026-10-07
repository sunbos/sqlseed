# API 参考 {#api-reference}

本页介绍 0.2.6 版本及其源码候选的 Python API。请按[安装指南](guide.md#installation)安装兼容的包集合；0.2.4 及更早版本并不包含这里的全部接口，例如 `FillOptions`。发布状态请查看 [发布记录](https://github.com/sunbos/sqlseed/releases)。主要入口函数和常用模型由 `sqlseed` 导出；其他类型使用下文列出的子包导入路径。

```python
import sqlseed

print(sqlseed.__version__)
```

---

## 公共 API {#public-api}

### `fill()`

向单张表中填充生成的测试数据。

```python
sqlseed.fill(
    db_path: str | None = None,
    *,
    url: str | None = None,
    table: str,
    count: int = 1000,
    options: sqlseed.FillOptions | None = None,
    **overrides: Unpack[_FillOverrides],
) -> GenerationResult
```

**参数**

| 参数 | 类型 | 默认值 | 说明 |
|-----------|------|---------|-------------|
| `db_path` | `str \| None` | `None` | SQLite 数据库文件路径，与 `url` 互斥。 |
| `url` | `str \| None` | `None` | 数据库 URL，例如 `postgresql+psycopg://user:pass@host/db`，与 `db_path` 互斥。 |
| `table` | `str` | — | 目标表名。**必填。** |
| `count` | `int` | `1000` | 要生成的行数。 |
| `options` | `FillOptions \| None` | `None` | 可复用的生成设置。下面的独立关键字参数会覆盖此对象中的值。 |
| `columns` | `dict[str, Any] \| None` | `None` | 各字段的生成配置。键为列名；值可以是生成器名称（`"email"`）或完整字典（`{"type": "integer", "min_value": 18}`）。 |
| `provider` | `str` | `"mimesis"` | 数据生成引擎：`mimesis`、`faker` 或 `base`。 |
| `locale` | `str` | `"en_US"` | 姓名、地址等本地化生成器使用的数据语言地区。 |
| `seed` | `int \| None` | `None` | 用于复现生成结果的随机种子。 |
| `batch_size` | `int` | `5000` | 每批插入的行数。较大值会以更多内存换取吞吐量。 |
| `clear_before` | `bool` | `False` | 生成前清空目标表。 |
| `optimize_pragma` | `bool` | `True` | 应用 SQLite PRAGMA 优化（journal_mode、synchronous 等）。 |
| `enrich` | `bool` | `False` | 根据已有数据推断字段分布。 |
| `transform` | `str \| None` | `None` | 逐行应用的 Python 转换脚本路径。 |
| `skip_ai` | `bool` | `True` | 跳过 AI 结构分析。 |

`columns` 到 `skip_ai` 仍接受独立的、带类型声明的关键字参数，默认值不变。未知关键字（包括 `snapshot`）会在打开连接前引发 `TypeError`。函数自省现在显示归组的 `options` 参数和带类型声明的 `overrides`，而不是将这些生成选项逐一列为独立参数。

**返回值**

[`GenerationResult`](#generationresult) 数据类，包含表名、行数、耗时和错误信息。

**异常与失败**

- `ValueError`：既未提供 `db_path` 也未提供 `url`，或同时提供了两者。
- 连接、配置和参数校验错误可能向调用方传播。
- 执行失败也可能以带有 `errors` 的 `GenerationResult` 返回。始终检查 `errors` 和 `count`；函数正常返回并不证明所有计划行都已写入。详见[失败语义](maintainable-release.md#write-semantics)。

**示例**

```python
import sqlseed

# SQLite
result = sqlseed.fill("app.db", table="users", count=10_000)
print(result.count, result.errors)

# PostgreSQL
result = sqlseed.fill(
    url="postgresql+psycopg://user:pass@localhost:5432/mydb",
    table="users",
    count=10_000,
    seed=42,
)

# Fine-grained column control
result = sqlseed.fill(
    "app.db",
    table="users",
    count=50_000,
    columns={
        "email": "email",
        "age": {"type": "integer", "min_value": 18, "max_value": 65},
    },
    provider="mimesis",
    locale="en_US",
    seed=42,
)
```

### `FillOptions`

这个冻结的、仅接受关键字参数的数据类，用于在多次调用之间复用上表中的生成设置。它包含上述十个字段，默认值相同；数据库目标、表名和行数由每次 `fill()` 调用单独指定。显式关键字参数始终优先，即使值为 `False`、`0` 或 `None`，也不会修改传入的设置对象。`columns` 字典本身仍可修改。

```python
settings = sqlseed.FillOptions(provider="faker", seed=42, batch_size=500)
result = sqlseed.fill("app.db", table="users", count=100, options=settings)
# Override the shared seed for this call only.
result = sqlseed.fill("app.db", table="users", count=100, options=settings, seed=None)
```

---

### `connect()`

连接数据库并返回 `DataOrchestrator` 上下文管理器。需要填充多张具有外键关系的表时，可以使用此入口。

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

**参数**

| 参数 | 类型 | 默认值 | 说明 |
|-----------|------|---------|-------------|
| `db_path` | `str \| None` | `None` | SQLite 文件路径，与 `url` 互斥。 |
| `url` | `str \| None` | `None` | 数据库 URL，与 `db_path` 互斥。 |
| `provider` | `str` | `"mimesis"` | 数据生成引擎名称。 |
| `locale` | `str` | `"en_US"` | 本地化生成器使用的数据语言地区。 |
| `optimize_pragma` | `bool` | `True` | 应用 SQLite PRAGMA 优化。 |

**返回值**

可用作上下文管理器的 [`DataOrchestrator`](#dataorchestrator) 实例。

**异常**

- `ValueError`：既未提供 `db_path` 也未提供 `url`，或同时提供了两者。

**示例**

```python
import sqlseed

with sqlseed.connect("app.db", provider="mimesis", locale="en_US") as db:
    db.fill("users", count=10_000, seed=42)
    db.fill("orders", count=50_000)  # FK to users.id auto-resolved
    print(db.report())
```

---

### `fill_from_config()`

读取 YAML/JSON 配置文件，按拓扑顺序填充所有声明的表（先处理被外键依赖的表）。配置中的全局参数可以通过关键字参数覆盖。

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

**参数**

| 参数 | 类型 | 默认值 | 说明 |
|-----------|------|---------|-------------|
| `config_path` | `str` | — | YAML 或 JSON 配置文件路径。**必填。** |
| `skip_ai` | `bool` | `True` | 跳过 AI 结构分析。 |
| `clear_before` | `bool` | `False` | 填充前清空各表（设为 `True` 时覆盖表级设置）。 |
| `count` | `int \| None` | `None` | 覆盖所有表的行数。 |
| `provider` | `str \| None` | `None` | 覆盖数据生成引擎。 |
| `seed` | `int \| None` | `None` | 覆盖所有表的随机种子。 |
| `batch_size` | `int \| None` | `None` | 覆盖所有表的批次大小。 |
| `locale` | `str \| None` | `None` | 覆盖数据语言地区。 |

**返回值**

按拓扑顺序排列的 [`GenerationResult`](#generationresult) 实例列表，每张表对应一个结果。

**示例**

```python
import sqlseed

results = sqlseed.fill_from_config("generate.yaml", seed=42)
for r in results:
    print(r.table_name, r.count, r.errors)
```

该示例保留每张表配置的 `clear_before` 设置，其默认值为 `False`。对于已有外键关系图，若在子表之前清空被引用的父表，可能发生失败，而后续表仍继续生成。请使用结构相同的新数据库，或明确先清空子表再清空父表；拓扑生成顺序不会让整张关系图的清空变为原子操作。

---

### `preview()`

预览生成数据，不写入数据库。可用于调试字段映射和生成器参数。

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

**参数**

| 参数 | 类型 | 默认值 | 说明 |
|-----------|------|---------|-------------|
| `db_path` | `str \| None` | `None` | SQLite 文件路径，与 `url` 互斥。 |
| `url` | `str \| None` | `None` | 数据库 URL，与 `db_path` 互斥。 |
| `table` | `str` | — | 目标表名。**必填。** |
| `count` | `int` | `5` | 预览行数。 |
| `columns` | `dict[str, Any] \| None` | `None` | 各字段的生成配置。 |
| `provider` | `str` | `"mimesis"` | 数据生成引擎名称。 |
| `locale` | `str` | `"en_US"` | 本地化生成器使用的数据语言地区。 |
| `seed` | `int \| None` | `None` | 用于复现预览结果的随机种子。 |
| `enrich` | `bool` | `False` | 根据已有数据推断分布。 |
| `transform` | `str \| None` | `None` | 转换脚本路径。 |

**返回值**

字典列表，每个字典将列名映射到生成值。

**异常**

- `ValueError`：既未提供 `db_path` 也未提供 `url`，或同时提供了两者。

**示例**

```python
import sqlseed

rows = sqlseed.preview("app.db", table="users", count=5, seed=42)
for row in rows:
    print(row)
# Example generated fields: {'name': 'John Smith', 'email': 'jsmith@example.com', ...}
# Database-generated IDs/defaults are not predicted by a preview.
```

---

### `load_config()`

将 YAML 或 JSON 配置文件读取为 `GeneratorConfig` 模型。根据文件扩展名（`.yaml`/`.yml` 或 `.json`）判断格式。

```python
from sqlseed import load_config

config = load_config(path: str) -> GeneratorConfig
```

**参数**

| 参数 | 类型 | 默认值 | 说明 |
|-----------|------|---------|-------------|
| `path` | `str` | — | YAML 或 JSON 配置文件路径。**必填。** |

**返回值**

已通过校验的 [`GeneratorConfig`](#generatorconfig) 实例。

**异常**

- `FileNotFoundError`：文件不存在。
- `ValueError`：文件内容未通过 Pydantic 校验。

**示例**

```python
from sqlseed import load_config

config = load_config("generate.yaml")
print(config.db_path, config.provider, len(config.tables))
```

---

## 配置模型 {#configuration-models}

配置模型是 `sqlseed.config.models` 中的 Pydantic `BaseModel` 子类。`ColumnConfig`、`GeneratorConfig`、`ProviderType` 和 `TableConfig` 也由 `sqlseed` 导出。`ColumnConstraintsConfig`、`ColumnAssociation` 和 `CustomColumnMappings` 从 `sqlseed.config.models` 导入。

### `GeneratorConfig`

全局生成配置。通过 `db_path`（SQLite 文件路径）**或** `url`（数据库 URL）指定连接目标；两者互斥，且至少必须提供一个。

```python
class GeneratorConfig(BaseModel):
    db_path: str | None = None
    url: str | None = None
    provider: ProviderType = ProviderType.MIMESIS
    locale: str = "en_US"
    tables: list[TableConfig] = []
    associations: list[ColumnAssociation] = []
    custom_column_mappings: CustomColumnMappings | None = None
    optimize_pragma: bool = True
    snapshot_dir: str | None = None
    log_level: str | None = None  # deprecated
```

**属性**

| 属性 | 类型 | 说明 |
|----------|------|-------------|
| `connection_target` | `str` | 若设置了 `url` 则返回它，否则返回 `db_path`。两者均未配置时抛出 `RuntimeError`。 |

**校验规则**

- `db_path` 与 `url` 互斥，同时提供会引发 `ValueError`。
- 必须提供 `db_path` 或 `url` 中的至少一个，都不提供会引发 `ValueError`。

---

### `TableConfig`

单表生成配置。

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

字段配置，支持两种互斥模式：

- **来源列模式**：指定 `generator` + `params` 生成取值。
- **派生列模式**：指定 `derive_from` + `expression`，根据同一行的另一列计算取值。

```python
class ColumnConfig(BaseModel):
    name: str

    # Source-column mode
    generator: str | None = None
    provider: ProviderType | None = None
    params: dict[str, Any] = {}
    null_ratio: float = 0.0     # 0.0–1.0

    # Derived-column mode
    derive_from: str | list[str] | None = None  # source column name(s)
    expression: str | None = None

    # Constraints
    constraints: ColumnConstraintsConfig | None = None

    # Native method overrides (from AI suggestions)
    faker_method: str | None = None
    mimesis_method: str | None = None
    native_params: dict[str, Any] = {}
```

**校验规则**

- `generator` 与 `derive_from` 不能同时使用。
- 使用 `derive_from` 时必须提供 `expression`。

**字典简写**

从字典构建时，未知键会自动合并到 `params`，`type` 被视为 `generator` 的别名：

```python
ColumnConfig(name="age", type="integer", min_value=18, max_value=65)
# Equivalent to:
ColumnConfig(name="age", generator="integer", params={"min_value": 18, "max_value": 65})
```

---

### `ColumnConstraintsConfig`

字段约束配置。`ConstraintSolver` 使用它进行唯一性回溯和取值范围约束。

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

跨表字段关联声明。在没有外键约束时，用于声明隐式关联（跨表同名列引用）。

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

受支持的数据生成引擎类型枚举。

```python
class ProviderType(str, Enum):
    BASE = "base"       # built-in synthesized values
    FAKER = "faker"     # Faker engine (required dep)
    MIMESIS = "mimesis" # Mimesis engine (optional, high-performance)
    CUSTOM = "custom"   # user-registered provider
```

---

## 结果类型 {#result-types}

### `GenerationResult`

`fill()` 和 `fill_from_config()` 返回的数据类，封装数据生成任务执行后的统计信息。`count` 是报告的实际插入行数，`batch_count` 是已完成的批次数。Core 常规分批执行中，失败批次会回滚，但之前已提交的批次可能保留。外层事务仍可能决定最终是否提交。请同时检查 `errors` 和 `count`；取消、中断与 Web 事务边界见[支持与维护](maintainable-release.md)。

```python
from dataclasses import dataclass, field


@dataclass
class GenerationResult:
    table_name: str
    count: int
    elapsed: float
    rows_per_second: float = 0.0     # auto-computed in __post_init__
    batch_count: int = 0
    errors: list[str] = field(default_factory=list)
```

**示例**

```python
result = sqlseed.fill("app.db", table="users", count=1000)
print(result.table_name)
print(result.count, result.errors)  # Actual writes and any failures
print(result.elapsed)              # Measured seconds for this run
print(result.rows_per_second)      # Computed from count and elapsed
print(str(result))
```

---

## `DataOrchestrator`

核心编排引擎，由 `connect()` 返回并作为上下文管理器使用。大多数用户通过 `connect()` 调用它，也可以直接实例化。

```python
from sqlseed import DataOrchestrator

with DataOrchestrator(
    db_path="app.db",            # or a PostgreSQL URL as the db_path value
    provider_name="mimesis",
    locale="en_US",
    optimize_pragma=True,
) as orch:
    orch.fill_table(table_name="users", count=1000, seed=42)
```

**主要方法**

| 方法 | 说明 |
|--------|-------------|
| `fill_table(...)` | 填充单张表。 |
| `preview_table(...)` | 预览记录，不写入数据库。 |
| `get_topological_table_order(names)` | 按外键依赖顺序返回表名。 |
| `get_column_mapping(table)` | 返回每列解析后的 `GeneratorSpec`。 |
| `get_column_info(table)` | 返回 `ColumnInfo` 列表。 |
| `get_foreign_keys(table)` | 返回 `ForeignKeyInfo` 列表。 |
| `get_row_count(table)` | 返回当前行数。 |
| `report()` | 读取数据库当前表名和行数，包含已有数据。 |

`DataOrchestrator` 还提供 `from_config(config)` 类方法，可根据 `GeneratorConfig` 构建实例。

---

## 数据库适配器协议 {#database-adapter-protocol}

### `DatabaseAdapter`

带有 `runtime_checkable` 的 `Protocol`，定义所有数据库适配器的契约。实现应提供结构自省、批量插入和事务管理。

```python
from sqlseed.database import DatabaseAdapter
```

**协议方法**

| 方法 | 签名 | 说明 |
|--------|-----------|-------------|
| `connect` | `(db_path: str) -> None` | 连接数据库。 |
| `close` | `() -> None` | 关闭连接。 |
| `get_table_names` | `() -> list[str]` | 列出所有用户表。 |
| `get_column_info` | `(table_name: str) -> list[ColumnInfo]` | 获取列元数据。 |
| `get_primary_keys` | `(table_name: str) -> list[str]` | 获取主键列名。 |
| `get_foreign_keys` | `(table_name: str) -> list[ForeignKeyInfo]` | 获取外键元数据。 |
| `get_row_count` | `(table_name: str) -> int` | 获取当前行数。 |
| `get_column_values` | `(table_name, column_name, limit=1000) -> list[Any]` | 抽取列值样本。 |
| `get_index_info` | `(table_name: str) -> list[IndexInfo]` | 获取索引元数据。 |
| `get_unique_constraints` | `(table_name: str) -> list[IndexInfo]` | 获取 UNIQUE 约束元数据（单列和多列）。 |
| `get_check_constraints` | `(table_name: str) -> list[CheckConstraintInfo]` | 获取 CHECK 约束元数据（原始 SQL 表达式与引用列）。 |
| `get_sample_rows` | `(table_name, limit=5) -> list[dict]` | 抽取样例行。 |
| `batch_insert` | `(table_name, data, batch_size=5000) -> int` | 从迭代器批量插入数据。 |
| `clear_table` | `(table_name: str) -> None` | 删除所有行。 |
| `optimize_for_bulk_write` | `(expected_rows: int \| None = None) -> None` | 应用写入优化。 |
| `restore_settings` | `() -> None` | 恢复默认设置。 |
| `execute` | `(sql, params=()) -> Any` | 执行原始 SQL。 |
| `__enter__` / `__exit__` | — | 支持上下文管理器。 |

**配套数据类**

```python
@dataclass(frozen=True)
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    default: Any
    is_primary_key: bool
    is_autoincrement: bool
    is_computed: bool = False
    is_rowid_alias: bool | None = None

@dataclass(frozen=True)
class ForeignKeyInfo:
    column: str
    ref_table: str
    ref_column: str
    constraint_id: int | None = None
    ref_schema: str | None = None

@dataclass(frozen=True)
class IndexInfo:
    name: str
    table: str
    columns: tuple[str, ...]
    unique: bool
    is_partial: bool = False
    predicate: str | None = None

@dataclass(frozen=True)
class CheckConstraintInfo:
    name: str
    table: str
    columns: tuple[str, ...]
    expression: str
```

`is_rowid_alias` 用于区分 SQLite 隐式 rowid 主键与其他主键；`None` 保留对旧版手工构造元数据的兼容。`constraint_id` 将同一外键约束的各列归为一组，`ref_schema` 保留反射得到的父表 schema。这些元数据字段不代表生成器支持所有可反射的关系。

部分索引只对满足其谓词的行施加唯一约束。`is_partial` 记录这一差异；能够获取时，`predicate` 保留反射出的 SQL。原始 SQLite 元数据可能不包含谓词文本。

---

### `SQLAlchemyAdapter`

生产使用**必须采用**的适配器。通过 SQLAlchemy 支持 SQLite 和 PostgreSQL，并根据连接 URL 自动识别方言。

```python
from sqlseed.database import SQLAlchemyAdapter
```

**连接形式**

| URL | 数据库 |
|-----|----------|
| `sqlite:///path/to/db` | SQLite |
| `postgresql+psycopg://user:pass@host/db` | PostgreSQL（需要 `sqlseed[postgres]`） |
| `/path/to/db.sqlite` | SQLite（自动转换为 `sqlite:///` URL） |

**方言属性**

`SQLAlchemyAdapter` 提供两个可选属性，其他适配器不一定实现：

- `dialect`：`Dialect` 实例（`SQLiteDialect`、`PostgresDialect` 等），提供方言专用的元数据查询。
- `bulk_optimizer`：`BulkWriteOptimizer` 实例，提供方言专用的批量写入策略。

上层代码通过 `hasattr(adapter, "dialect")` 检查是否支持。

---

### `RawSQLiteAdapter`

基于 Python 内置 `sqlite3` 模块的**仅供测试使用**的适配器。不使用第三方依赖，适用于零依赖测试场景。

```python
from sqlseed.database import RawSQLiteAdapter
```

!!! warning "不用于生产"

    `RawSQLiteAdapter` 没有实现 `dialect` 或 `bulk_optimizer` 属性，且仅支持 SQLite。生产使用应选择 `SQLAlchemyAdapter`，以获得多方言支持和批量写入优化。

**示例**

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

## 模块导出 {#module-exports}

顶层 `sqlseed` 包导出以下名称：

```python
__all__ = [
    "ColumnConfig",
    "DataOrchestrator",
    "FillOptions",
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

`sqlseed.database` 子包还导出以下名称：

```python
__all__ = [
    "BulkWriteOptimizer",
    "CheckConstraintInfo",
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
