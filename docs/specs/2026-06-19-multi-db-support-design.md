# 多数据库支持设计文档

**日期**: 2026-06-19
**状态**: 设计阶段
**分支**: `feat/multi-db-support`（待创建）
**目标**: 将 sqlseed 从 SQLite-only 扩展为支持 PostgreSQL（第一阶段）及更多数据库

---

## 1. 背景与动机

### 1.1 当前状态

sqlseed 当前仅支持 SQLite，数据库适配层有两个实现：

- `RawSQLiteAdapter` — 基于 Python 标准库 `sqlite3`
- `SQLiteUtilsAdapter` — 基于 `sqlite-utils` 第三方库

代码中深度耦合 SQLite 专属语法（`PRAGMA`、`sqlite_master`、`sqlite_sequence`、`PRAGMA table_info` 等），无法直接扩展到其他数据库。

### 1.2 改造目标

- 第一阶段支持 PostgreSQL，验证抽象设计是否充分
- 保持现有 SQLite 用户体验零回归
- 为未来支持 MySQL、DuckDB 等数据库预留扩展点

### 1.3 核心约束

- **主分支零改动**：所有开发在 `feat/multi-db-support` 分支进行，全部测试通过后才能合并
- **向后兼容**：现有 API、CLI、配置文件格式不变
- **渐进式重构**：分四个阶段，每阶段独立可验证

---

## 2. 关键决策

| 决策点 | 结论 | 理由 |
|--------|------|------|
| 第一阶段数据库 | PostgreSQL | 最接近标准 SQL，与 SQLite 差异最大，能充分验证抽象 |
| 适配器策略 | SQLAlchemy 统一适配器 | 屏蔽数据库差异，减少重复代码 |
| AI 插件 | 与数据库解耦，context 传入 dialect | AI 消费的是 `ColumnInfo` 等抽象数据结构，无需感知底层 |
| MCP 定位 | 专注生成 + 搭配通用 MCP | 与 `mcp-server-sql` 等通用 MCP 互补 |
| SQLAlchemy 依赖 | 核心依赖 | 简化代码路径，SQLite 方言用内置 `sqlite3` 零额外依赖 |
| 数据库驱动 | 可选插件 | `sqlseed[postgres]`、`sqlseed[mysql]` 按需安装 |
| sqlite-utils | 退役 | sqlseed 仅用其 10% 功能，SQLAlchemy 完全覆盖 |
| 实现路径 | 渐进式重构（方案 A） | 风险最低，每阶段独立可验证 |

---

## 3. 依赖模型

### 3.1 安装方式

```bash
# SQLite 开箱即用（SQLAlchemy 的 SQLite 方言用内置 sqlite3）
pip install sqlseed

# PostgreSQL 支持
pip install sqlseed[postgres]

# MySQL 支持（未来）
pip install sqlseed[mysql]

# 所有数据库 + 生成器
pip install sqlseed[all]
```

### 3.2 驱动缺失处理

当用户连接未安装驱动的数据库时，SQLAlchemy 抛出 `NoSuchModuleError`，sqlseed 捕获后给出友好提示：

```
RuntimeError: PostgreSQL driver not installed.
Install with: pip install sqlseed[postgres]
```

### 3.3 依赖变化

| 依赖 | 阶段 1 | 阶段 2 | 阶段 3 | 阶段 4 |
|------|--------|--------|--------|--------|
| `sqlalchemy>=2.0` | - | 核心 | 核心 | 核心 |
| `psycopg[binary]>=3.0` | - | - | 可选[postgres] | 可选[postgres] |
| `sqlite-utils` | 可选 | 可选 | 可选 | **移除** |
| `faker` | 可选 | 可选 | 可选 | 可选 |
| `mimesis` | 可选 | 可选 | 可选 | 可选 |

---

## 4. 数据库层架构

### 4.1 目录结构

```
src/sqlseed/database/
├── _protocol.py            # DatabaseAdapter 协议（演进）
├── _dialect.py             # 新增：Dialect 协议 + 各方言实现
├── _type_normalizer.py     # 新增：TypeNormalizer 类型归一化
├── _bulk_optimizer.py      # 新增：BulkWriteOptimizer 协议 + 各方言实现
├── sqlalchemy_adapter.py   # 新增：SQLAlchemyAdapter
├── raw_sqlite_adapter.py   # 阶段 1-3 保留；阶段 4 可选保留作为无 SQLAlchemy 回退
├── sqlite_utils_adapter.py # 阶段 1-3 保留；阶段 4 删除
├── optimizer.py            # 保留，SQLiteBulkOptimizer 内部委托给它
├── _base_adapter.py        # 阶段 1-3 保留；阶段 4 评估是否重构
├── _helpers.py             # 保留
├── _compat.py              # 阶段 1-3 保留；阶段 4 删除（随 sqlite_utils_adapter 退役）
└── __init__.py             # 导出更新
```

### 4.2 Dialect 协议

封装各数据库的专属行为，让上层代码无需感知底层方言。

```python
# _dialect.py
from __future__ import annotations
from typing import Protocol, runtime_checkable
from collections.abc import Callable


@runtime_checkable
class Dialect(Protocol):
    """数据库方言抽象，封装各数据库的专属行为"""

    name: str  # "sqlite", "postgresql", "mysql"

    def normalize_type(self, raw_type: str) -> str:
        """将数据库原始类型名归一化为 sqlseed 内部类型
        SQLite: "TEXT" → "TEXT", "INTEGER" → "INTEGER"
        PG: "character varying(255)" → "VARCHAR(255)"
        """
        ...

    def detect_autoincrement(self, column_info: dict) -> bool:
        """检测列是否自增
        SQLite: 解析 CREATE TABLE 找 AUTOINCREMENT
        PG: 检测 SERIAL / IDENTITY / nextval()
        """
        ...

    def reset_autoincrement(self, execute_fn: Callable[..., object], table_name: str) -> None:
        """重置自增计数器
        SQLite: DELETE FROM sqlite_sequence
        PG: TRUNCATE ... RESTART IDENTITY / ALTER SEQUENCE
        MySQL: ALTER TABLE ... AUTO_INCREMENT = 1
        """
        ...

    def quote_identifier(self, name: str) -> str:
        """引用标识符
        SQLite/PG: "name"
        MySQL: `name`
        """
        ...

    def create_batch_inserter(self, engine: object, table_name: str) -> BatchInserter:
        """创建批量写入器
        SQLite: SQLAlchemy bulk_insert_mappings
        PG: psycopg3 COPY 协议（比 INSERT 快 5-10x）
        """
        ...


class BatchInserter(Protocol):
    """批量写入器接口"""
    def insert(self, rows: list[dict]) -> int: ...
```

### 4.3 SQLiteDialect 实现

```python
class SQLiteDialect:
    name = "sqlite"

    def normalize_type(self, raw_type: str) -> str:
        # SQLite 类型已经是规范化的大写形式
        return raw_type.upper() if raw_type else "TEXT"

    def detect_autoincrement(self, column_info: dict) -> bool:
        # 委托给现有的 schema_helpers.detect_autoincrement
        # 解析 CREATE TABLE SQL 找 AUTOINCREMENT 关键字
        ...

    def reset_autoincrement(self, execute_fn, table_name: str) -> None:
        execute_fn("DELETE FROM sqlite_sequence WHERE name = ?", [table_name])

    def quote_identifier(self, name: str) -> str:
        escaped = name.replace('"', '""')
        return f'"{escaped}"'

    def create_batch_inserter(self, engine, table_name: str) -> BatchInserter:
        return SQLAlchemyBatchInserter(engine, table_name)
```

### 4.4 PostgresDialect 实现

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
        # 提取基础类型和修饰符
        # "character varying(255)" → "VARCHAR(255)"
        # "numeric(10,2)" → "NUMERIC(10,2)"
        ...

    def detect_autoincrement(self, column_info: dict) -> bool:
        # 三重检测：
        # 1. SQLAlchemy 的 identity 属性 (GENERATED ... AS IDENTITY)
        # 2. default 值含 nextval (SERIAL 模式)
        # 3. autoincrement 标志 (SQLAlchemy 对整数 PK 的推断)
        if column_info.get("identity") is not None:
            return True
        default = column_info.get("default")
        if default and "nextval" in str(default):
            return True
        if column_info.get("autoincrement"):
            return True
        return False

    def reset_autoincrement(self, execute_fn, table_name: str) -> None:
        # PG 重置序列：ALTER SEQUENCE <seq> RESTART WITH 1
        # 需要先查出表对应的序列名
        ...

    def quote_identifier(self, name: str) -> str:
        escaped = name.replace('"', '""')
        return f'"{escaped}"'

    def create_batch_inserter(self, engine, table_name: str) -> BatchInserter:
        return PostgresCopyInserter(engine, table_name)
```

### 4.5 TypeNormalizer

保护 `mapper.py` 中 74 条 exact match 规则不失效。

```python
# _type_normalizer.py
from __future__ import annotations
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedType:
    """归一化后的类型信息"""
    base: str           # "VARCHAR"
    params: tuple       # (255,) 或 (10, 2)
    raw: str            # 原始 "character varying(255)"

    @property
    def display(self) -> str:
        """显示形式："VARCHAR(255)" 或 "INTEGER" """
        if self.params:
            return f"{self.base}({','.join(str(p) for p in self.params)})"
        return self.base


_TYPE_PARAMS_RE = re.compile(r"^([^(]+)\s*(?:\(([^)]+)\))?")


class TypeNormalizer:
    """将不同数据库的类型名归一化，让 mapper.py 的规则继续工作"""

    def normalize(self, raw_type: str, dialect_name: str) -> NormalizedType:
        # 1. 提取基础类型名和参数
        match = _TYPE_PARAMS_RE.match(raw_type.strip())
        if not match:
            return NormalizedType(base=raw_type.upper(), params=(), raw=raw_type)

        base_raw = match.group(1).strip().lower()
        params_str = match.group(2)

        # 2. 方言映射
        base = self._map_base_type(base_raw, dialect_name)

        # 3. 解析参数
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

### 4.6 BulkWriteOptimizer 协议

```python
# _bulk_optimizer.py
from __future__ import annotations
from typing import Protocol


class BulkWriteOptimizer(Protocol):
    """批量写入性能优化器"""

    def preserve(self) -> None:
        """保存当前数据库配置"""
        ...

    def optimize(self, expected_rows: int | None = None) -> None:
        """应用批量写入优化
        SQLite: PRAGMA synchronous = OFF, journal_mode = MEMORY
        PG: SET synchronous_commit = OFF
        MySQL: SET unique_checks = 0
        """
        ...

    def restore(self) -> None:
        """恢复原配置"""
        ...


class SQLiteBulkOptimizer:
    """现有 PragmaOptimizer 重构而来"""
    # 委托给 optimizer.py 的 PragmaOptimizer


class PostgresBulkOptimizer:
    """PG 批量写入优化"""
    # SET synchronous_commit = OFF
    # 可选: ALTER TABLE ... SET UNLOGGED（数据可重建时）


class MySQLBulkOptimizer:
    """MySQL 批量写入优化"""
    # ALTER TABLE ... DISABLE KEYS
    # SET unique_checks = 0
    # SET foreign_key_checks = 0
```

### 4.7 DatabaseAdapter 协议演进

```python
# _protocol.py — 新增属性（可选，带默认实现）
@runtime_checkable
class DatabaseAdapter(Protocol):
    # ... 现有方法不变 ...

    @property
    def dialect(self) -> Dialect:
        """数据库方言"""
        ...

    @property
    def bulk_optimizer(self) -> BulkWriteOptimizer | None:
        """批量写入优化器（可选）"""
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
    """基于 SQLAlchemy 的统一数据库适配器"""

    def __init__(self) -> None:
        self._engine = None
        self._inspector = None
        self._dialect = None
        self._optimizer = None
        self._db_url = ""

    def connect(self, db_url: str) -> None:
        """支持多种连接方式：
        "sqlite:///path/to/db"           → SQLite
        "postgresql://user:pass@host/db" → PostgreSQL
        "mysql+pymysql://user:pass@host/db" → MySQL
        也兼容纯文件路径: "/path/to/db.sqlite" → 自动转为 sqlite:/// URL
        """
        # 纯文件路径自动转为 SQLite URL
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
            # 阶段 3 不实现，未来扩展
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
        # 使用 Dialect 提供的批量写入器
        inserter = self._dialect.create_batch_inserter(self._engine, table_name)
        return batch_insert_rows(data, batch_size, inserter.insert)

    def clear_table(self, table_name: str) -> None:
        with self._engine.connect() as conn:
            conn.execute(text(f"DELETE FROM {self._dialect.quote_identifier(table_name)}"))
            self._dialect.reset_autoincrement(conn.execute, table_name)
            conn.commit()

    # ... 其他方法实现 ...
```

### 4.9 Orchestrator 派发逻辑

```python
# orchestrator.py — _create_adapter 演进
def _create_adapter(self) -> DatabaseAdapter:
    # 如果用户传了 URL (postgresql://, mysql://)
    if self._db_url and "://" in self._db_url:
        return SQLAlchemyAdapter()

    # 向后兼容: 纯文件路径优先走 SQLAlchemy SQLite 方言
    if HAS_SQLALCHEMY:
        return SQLAlchemyAdapter()

    # 回退: 无 SQLAlchemy 时走 RawSQLiteAdapter
    return RawSQLiteAdapter()
```

### 4.10 sql_safe.py 改造

保留安全验证层，引用逻辑委托给 Dialect。

```python
# sql_safe.py — 改造后
def quote_identifier(name: str, *, dialect: Dialect | None = None) -> str:
    name = _sanitize_identifier(name)  # 安全验证不变
    if dialect is not None:
        return dialect.quote_identifier(name)
    # 回退: 默认用 SQL 标准双引号
    escaped = name.replace('"', '""')
    return f'"{escaped}"'


def build_insert_sql(
    table_name: str,
    column_names: list[str],
    *,
    dialect: Dialect | None = None,
) -> str:
    """构建安全的 INSERT SQL 语句
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

## 5. AI 插件改造

### 5.1 原则

AI 插件只消费 `ColumnInfo`/`ForeignKeyInfo` 等数据库无关的数据结构，不感知底层是 SQLite 还是 PG。

### 5.2 改动范围

| 文件 | 改动 | 原因 |
|------|------|------|
| `analyzer.py` SYSTEM_PROMPT | `"SQLite table schemas"` → `"database table schemas"` | 去硬编码 |
| `analyzer.py` Key Rules | `"INTEGER PRIMARY KEY AUTOINCREMENT"` → `"auto-incrementing primary keys"` | 通用描述 |
| `analyzer.py` GEMMA_TOOLS | `is_autoincrement` 描述改为通用 | 通用描述 |
| `analyzer.py` analyze_table_from_ctx | 新增 `dialect: str = "sqlite"` 参数 | 让 AI 知道目标数据库类型 |
| `__init__.py` hook | `sqlseed_ai_analyze_table` 传入 dialect 信息 | 适配新签名 |

### 5.3 Prompt 改造

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
... (其余规则不变)
"""
```

### 5.4 Schema Context 传入 dialect

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
    dialect: str = "sqlite",  # 新增
) -> dict:
    # dialect 信息传入 prompt，让 AI 知道目标数据库类型
    # 但 AI 的输出格式不变，仍然是 ColumnConfig JSON
    ...
```

---

## 6. MCP Server 改造

### 6.1 原则

专注数据生成，搭配通用 MCP 使用。

### 6.2 改动范围

| 文件 | 改动 | 原因 |
|------|------|------|
| `server.py` `_validate_db_path` | → `_validate_db_target`，支持 URL | 多数据库 |
| `server.py` 所有 tool 函数 | `db_path: str` 参数支持 URL | 多数据库 |
| `server.py` `DataOrchestrator(...)` | 适配新签名 | 多数据库 |

### 6.3 _validate_db_target 改造

```python
def _validate_db_target(db_target: str) -> str:
    """验证数据库连接目标，支持文件路径和 URL"""
    # URL 格式: postgresql://user:pass@host/db
    if "://" in db_target:
        return db_target  # URL 直接通过，后续由 SQLAlchemy 验证

    # 文件路径: 保持现有验证逻辑
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

## 7. 公共 API 演进

### 7.1 Python API

```python
# src/sqlseed/__init__.py

def connect(
    db_path: str | None = None,   # 向后兼容: SQLite 文件路径
    *,
    url: str | None = None,       # 新增: 数据库 URL
    **kwargs,
) -> DataOrchestrator:
    """连接数据库，返回 DataOrchestrator 上下文管理器

    支持两种连接方式：
    - connect("app.db")                              → SQLite 文件
    - connect(url="postgresql://user:pass@host/db")  → 数据库 URL
    """
    target = url or db_path
    if not target:
        raise ValueError("Either db_path or url must be provided")
    return DataOrchestrator(target, **kwargs)


def fill(
    db_path: str | None = None,
    *,
    url: str | None = None,       # 新增
    table: str,
    count: int,
    **kwargs,
) -> FillResult:
    """单表零配置填充"""
    target = url or db_path
    if not target:
        raise ValueError("Either db_path or url must be provided")
    with DataOrchestrator(target) as orch:
        return orch.fill_table(table_name=table, count=count, **kwargs)
```

### 7.2 CLI

```bash
# 现有用法不变
sqlseed fill app.db -t users -n 10000

# 新增 URL 支持（自动识别）
sqlseed fill "postgresql://user:pass@localhost/mydb" -t users -n 10000

# 显式 --url 参数
sqlseed fill --url "postgresql://user:pass@localhost/mydb" -t users -n 10000
```

### 7.3 配置文件

YAML 配置新增 `url` 字段，与 `db_path` 互斥：

```yaml
# 现有格式不变
db_path: app.db

# 新增 URL 格式
url: postgresql://user:pass@localhost/mydb
```

`GeneratorConfig` Pydantic 模型新增 `url` 字段，通过 `model_validator` 确保与 `db_path` 互斥。

---

## 8. 测试策略

### 8.1 验证命令

每个阶段必须通过四条验证命令才能进入下一阶段：

```bash
ruff check . && ruff format --check . && mypy src plugins && pytest
```

### 8.2 测试层次

| 测试类型 | 位置 | 目的 |
|---------|------|------|
| 契约测试 | `tests/test_database_contract.py` | 对所有适配器跑同一套接口测试，确保行为一致 |
| 方言测试 | `tests/test_dialect.py` | 验证 TypeNormalizer、quote_identifier、autoincrement 检测 |
| 集成测试 | `tests/test_postgres_integration.py` | 真实 PG 连接测试，标记 `@pytest.mark.postgres` |
| 回归测试 | 现有 `tests/` | 确保现有 618 个测试全部通过 |

### 8.3 契约测试设计

```python
# tests/test_database_contract.py
"""所有 DatabaseAdapter 实现必须通过的契约测试"""

class DatabaseAdapterContract:
    """子类化并提供 fixture 即可自动测试所有适配器"""

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

### 8.4 PG 集成测试 CI

```yaml
# .github/workflows/test.yml — 新增 PG 服务
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

## 9. 四阶段迁移计划

### 阶段 1: 抽象 Dialect + BulkWriteOptimizer + TypeNormalizer

**目标**: 抽出接口，现有代码零改动

**新增文件**:
- `src/sqlseed/database/_dialect.py` — Dialect 协议 + SQLiteDialect 实现
- `src/sqlseed/database/_type_normalizer.py` — TypeNormalizer + NormalizedType
- `src/sqlseed/database/_bulk_optimizer.py` — BulkWriteOptimizer 协议 + SQLiteBulkOptimizer

**修改文件**:
- `src/sqlseed/database/_protocol.py` — DatabaseAdapter 新增 `dialect` 和 `bulk_optimizer` 属性（可选，带默认实现）
- `src/sqlseed/database/__init__.py` — 导出新类

**不动的文件**:
- `raw_sqlite_adapter.py` — 零改动
- `sqlite_utils_adapter.py` — 零改动
- `optimizer.py` — 保留，SQLiteBulkOptimizer 内部委托给它

**验证**: 现有 618 测试全部通过 + 新增契约测试框架

### 阶段 2: 引入 SQLAlchemyAdapter

**目标**: 新增 SQLAlchemy 适配器，与现有适配器并存

**新增文件**:
- `src/sqlseed/database/sqlalchemy_adapter.py` — SQLAlchemyAdapter 实现

**修改文件**:
- `pyproject.toml` — dependencies 新增 `sqlalchemy>=2.0`
- `src/sqlseed/database/__init__.py` — 导出 SQLAlchemyAdapter
- `src/sqlseed/core/orchestrator.py` — `_create_adapter()` 增加 SQLAlchemy 路径

**新增测试**:
- `tests/test_database_contract.py` — SQLAlchemySQLiteContract 契约测试

**验证**: 现有测试通过 + SQLAlchemy SQLite 方言通过契约测试

### 阶段 3: PostgreSQL 支持

**目标**: 完整支持 PostgreSQL

**新增文件**:
- `src/sqlseed/database/_dialect.py` — 新增 PostgresDialect
- `src/sqlseed/database/_bulk_optimizer.py` — 新增 PostgresBulkOptimizer
- `tests/test_postgres_integration.py` — PG 集成测试

**修改文件**:
- `pyproject.toml` — 新增 `[project.optional-dependencies] postgres = ["psycopg[binary]>=3.0"]`
- `src/sqlseed/core/orchestrator.py` — `_create_adapter()` 支持 URL 派发
- `src/sqlseed/__init__.py` — `connect()` / `fill()` 支持 `url` 参数
- `src/sqlseed/cli/main.py` — CLI 支持 `--url` 参数
- `src/sqlseed/config/models.py` — GeneratorConfig 新增 `url` 字段
- `plugins/sqlseed-ai/src/sqlseed_ai/analyzer.py` — Prompt 去 SQLite 硬编码
- `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/server.py` — `_validate_db_target` 支持 URL

**验证**: 现有测试通过 + PG 集成测试通过

### 阶段 4: 清理

**目标**: 退役旧适配器和 sqlite-utils

**删除文件**:
- `src/sqlseed/database/sqlite_utils_adapter.py`
- `src/sqlseed/database/_compat.py`

**修改文件**:
- `pyproject.toml` — 移除 `sqlite-utils` 可选依赖
- `src/sqlseed/database/__init__.py` — 移除旧导出
- `src/sqlseed/core/orchestrator.py` — 移除旧适配器引用

**评估保留**:
- `raw_sqlite_adapter.py` — 评估是否保留作为无 SQLAlchemy 的回退（取决于社区需求）
- `_base_adapter.py` — 评估是否重构或保留（取决于 RawSQLiteAdapter 的去留）

**验证**: 全量测试通过 + 文档同步更新

---

## 10. 文档同步规则

根据项目 `CLAUDE.md` 的 Doc Sync Rules，以下文档需在对应阶段同步更新：

| 阶段 | 源文件 | 需更新的文档 |
|------|--------|-------------|
| 阶段 2 | `_protocol.py`, `sqlalchemy_adapter.py` | README.md, README.zh-CN.md, docs/architecture.md |
| 阶段 3 | `__init__.py`, `cli/main.py`, `config/models.py` | README.md, README.zh-CN.md (API 表 + CLI 参考) |
| 阶段 3 | `analyzer.py` | README.md, README.zh-CN.md (AI CLI 参考) |
| 阶段 4 | `pyproject.toml` | README.md (依赖说明) |

---

## 11. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| SQLAlchemy 引入导致性能回归 | SQLite 批量写入变慢 | 阶段 2 用契约测试对比性能，必要时保留 RawSQLiteAdapter |
| PG autoincrement 检测不准 | 数据生成异常 | 三重检测（identity + nextval + autoincrement 标志） |
| 类型归一化遗漏 | mapper.py 规则失效 | 完整的 PG/MySQL 类型映射表 + 单元测试覆盖 |
| 主分支被污染 | 稳定版本受损 | 严格分支隔离，每阶段验证通过才合并 |
| 现有测试回归 | 功能损坏 | 每阶段跑全量 618 测试 |

---

## 12. 成功标准

- [ ] 阶段 1: 现有 618 测试全部通过 + 契约测试框架就绪
- [ ] 阶段 2: SQLAlchemy SQLite 方言通过契约测试 + 性能不劣于 RawSQLiteAdapter
- [ ] 阶段 3: PG 集成测试通过 + `sqlseed fill "postgresql://..." -t users -n 10000` 可用
- [ ] 阶段 4: sqlite-utils 退役 + 全量测试通过 + 文档同步完成
- [ ] 全程: 主分支零改动，所有开发在 `feat/multi-db-support` 分支
