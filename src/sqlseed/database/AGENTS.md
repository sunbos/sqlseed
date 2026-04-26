# AGENTS.md — src/sqlseed/database

## 作用域

- 本目录拥有 `DatabaseAdapter` Protocol、SQLite 元数据 dataclass、共享基类 `BaseSQLiteAdapter`、两套 SQLite 适配器，以及 PRAGMA 优化器。

## 文件清单

| 文件 | 职责 |
|------|------|
| `_protocol.py` | `DatabaseAdapter` Protocol、`ColumnInfo`/`ForeignKeyInfo`/`IndexInfo` frozen dataclass |
| `_base_adapter.py` | `BaseSQLiteAdapter` 共享基类（提供 `get_index_info`、`get_sample_rows`、`get_column_values`、`optimize_for_bulk_write`、`restore_settings` 等通用实现） |
| `_compat.py` | `HAS_SQLITE_UTILS` 标志与 `sqlite_utils` 模块引用（可选依赖兼容层） |
| `_helpers.py` | `fetch_index_info()`、`fetch_sample_rows()`、`batch_insert_rows()`、`apply_pragma_optimize()`、`apply_pragma_restore()` 共享辅助函数 |
| `optimizer.py` | `PragmaOptimizer`（preserve/optimize/restore 三级策略）、`PragmaProfile` dataclass |
| `raw_sqlite_adapter.py` | `RawSQLiteAdapter(BaseSQLiteAdapter)` — 原生 sqlite3 实现 |
| `sqlite_utils_adapter.py` | `SQLiteUtilsAdapter(BaseSQLiteAdapter)` — sqlite-utils 实现 |

## 本目录规则

- 保持 `SQLiteUtilsAdapter` 与 `RawSQLiteAdapter` 的可观察行为尽量一致；如果只能改一条路径，必须明确这是兼容性差异并补对应测试。
- 表名、列名和拼接 SQL 一律经过 `validate_table_name()`、`quote_identifier()` 或 `build_insert_sql()`；不要引入新的手写 SQL 标识符拼接。
- 继续保留 `sqlite-utils` 可选依赖边界。核心包在缺失 `sqlite_utils` 时仍应能导入，并回退到原生 sqlite3 路径。`_compat.py` 的 `HAS_SQLITE_UTILS` 标志控制此行为。
- `BaseSQLiteAdapter` 提供共享实现，子类需实现 `_get_execute_fn()`、`get_column_info()`、`close()` 三个抽象方法。新增通用方法应优先加到基类。
- `_helpers.py` 中的 `fetch_index_info()` 会跳过 `sqlite_autoindex_` 前缀的自动索引。
- `PragmaOptimizer` 的 preserve / optimize / restore 是成组语义。改阈值、profile 或 restore 逻辑时，同时检查 orchestrator 的 `finally` 路径。
- `_protocol.py` 里的 `ColumnInfo`、`ForeignKeyInfo`、`IndexInfo` 是上层 schema、AI、MCP 共享的数据形状；新增字段或改名会波及多个边界。
- 清表、批量插入和 `DEFAULT VALUES` 语义要兼顾空行批次与事务提交；不要只修一套适配器。
- `RawSQLiteAdapter.clear_table()` 同时清理 `sqlite_sequence` 表以重置 AUTOINCREMENT 计数器，并显式 `commit()`。
- `SQLiteUtilsAdapter.clear_table()` 同样清理 `sqlite_sequence`，但无显式 `commit()`（依赖 sqlite-utils 自动事务管理）。
- `SQLiteUtilsAdapter.batch_insert()` 对 `None` 行用 `item or {}` 替换，空行走 `INSERT INTO table DEFAULT VALUES` 逐行插入。
- `RawSQLiteAdapter.restore_settings()` 覆盖基类实现，在恢复 PRAGMA 后额外执行 `commit()`。

## 两套适配器行为差异

| 方面 | RawSQLiteAdapter | SQLiteUtilsAdapter |
|------|------------------|---------------------|
| 底层库 | `sqlite3`（标准库） | `sqlite-utils`（可选依赖） |
| 类型获取 | `PRAGMA table_info()` 直接返回字符串 | `col.type` 可能是 Python 类型类，需 `str()` 转换 |
| 主键/FK 异常 | 无异常处理 | 捕获 `ValueError/KeyError/AttributeError`，返回空列表 |
| 批量插入 | `executemany()` + `build_insert_sql()` | `table.insert_all()` / DEFAULT VALUES 回退 |
| 空行处理 | 不处理 None 行 | `item or {}` 替换 None 行 |
| 清表后提交 | 显式 `commit()` | 无显式 `commit()` |
| 恢复设置 | 覆盖基类，额外 `commit()` | 使用基类实现 |
| 不可用时的行为 | 始终可用 | `connect()` 抛 `RuntimeError` |

## PRAGMA 三级优化阈值

| 级别 | 阈值 | PRAGMA 设置 |
|------|------|-------------|
| LIGHT | ≤ 10,000 行 | synchronous=NORMAL, temp_store=MEMORY, cache_size=-8000 |
| MODERATE | 10,001 ~ 100,000 行 | + journal_mode=MEMORY, mmap_size=256MB |
| AGGRESSIVE | > 100,000 行 | + journal_mode=OFF, mmap_size=512MB, page_size=4096 |

默认 `expected_rows` 为 10,000（即 None 时）。

## 评审热点

- `raw_sqlite_adapter.py` 依赖 `_utils.sql_safe` 生成安全 SQL；这里的回归通常会在 `tests/test_database/test_sql_safe.py` 和集成测试一起暴露。
- `sqlite_utils_adapter.py` 需要兼容第三方库返回值形状，异常分支通常应软化成空列表或稳定错误，而不是把 AttributeError 直接抛给上层。
- `optimizer.py` 的 restore 只恢复安全的 PRAGMA 值（`int`/`float` 直接写入，`str` 需匹配 `^[a-zA-Z0-9_-]+$`）；放宽校验前先确认不会把不可信值拼回 SQL。

## 验证

- 数据库层：`pytest tests/test_database`
- 关联集成：`pytest tests/test_orchestrator.py tests/test_schema.py tests/test_relation.py`
