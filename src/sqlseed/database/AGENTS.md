<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# database

## Purpose

SQLite 数据库访问的抽象层。提供统一的 `DatabaseAdapter` Protocol 和两种实现（RawSQLite + SQLiteUtils）。

## Key Files

| File | Description |
|------|-------------|
| `_protocol.py` | `DatabaseAdapter` Protocol 接口，`ColumnInfo`/`ForeignKeyInfo`/`IndexInfo` 数据类 |
| `_base_adapter.py` | `BaseSQLiteAdapter` 公共基类，提取两种适配器的共享逻辑 |
| `raw_sqlite_adapter.py` | `RawSQLiteAdapter` 纯 sqlite3 实现，零外部依赖 |
| `sqlite_utils_adapter.py` | `SQLiteUtilsAdapter` 基于 sqlite-utils 的实现（可选依赖） |
| `optimizer.py` | `PragmaOptimizer` 批量写入时的 PRAGMA 优化，`PragmaProfile` 配置 |
| `_compat.py` | 兼容性层，`HAS_SQLITE_UTILS` 标志和条件导入 |
| `_helpers.py` | 共享辅助函数（如 `batch_insert_rows`） |

## 双适配器行为差异

| 方面 | RawSQLiteAdapter | SQLiteUtilsAdapter |
|------|------------------|---------------------|
| 底层库 | `sqlite3`（标准库） | `sqlite-utils`（可选依赖） |
| 类型获取 | `PRAGMA table_info()` 直接返回字符串 | `col.type` 可能是 Python 类型类，需 `str()` 转换 |
| 主键/FK 异常 | 无异常处理 | 捕获 `ValueError/KeyError/AttributeError`，返回空列表 |
| 批量插入 | `executemany()` + `build_insert_sql()` | `table.insert_all()` / DEFAULT VALUES 回退 |
| 空行处理 | 不处理 None 行 | `item or {}` 替换 None 行 |
| 清表后提交 | 显式 `commit()` | 无显式 `commit()` |
| 清表清理 | 清理 `sqlite_sequence` 表重置 AUTOINCREMENT | 同样清理 `sqlite_sequence` |
| 恢复设置 | 覆盖基类，额外 `commit()` | 覆盖基类，额外两次 `commit()` + `super().restore_settings()` |
| 不可用时的行为 | 始终可用 | `connect()` 抛 `RuntimeError` |

## PRAGMA 三级优化阈值

| 级别 | 阈值 | synchronous | cache_size | journal_mode | temp_store | mmap_size | page_size |
|------|------|-------------|------------|--------------|------------|-----------|-----------|
| LIGHT | ≤ 10,000 行 | NORMAL | -8000 | — | MEMORY | — | — |
| MODERATE | 10,001 ~ 100,000 行 | OFF | -16000 | MEMORY | MEMORY | 256MB | — |
| AGGRESSIVE | > 100,000 行 | OFF | -32000 | OFF | MEMORY | 512MB | 4096 |

默认 `expected_rows` 为 10,000（即 None 时）。restore 只恢复安全的 PRAGMA 值（`int`/`float` 直接写入，`str` 需匹配 `^[a-zA-Z0-9_-]+$`）。

## For AI Agents

### Working In This Directory

- 新适配器必须实现 `DatabaseAdapter` Protocol 的所有方法
- SQL 拼接禁止使用 f-string 或字符串拼接，必须使用 `_utils.sql_safe` 模块的 `quote_identifier`/`build_insert_sql`
- sqlite-utils 为可选依赖，导入时必须通过 `_compat.py` 的 `HAS_SQLITE_UTILS` 检查
- `PragmaOptimizer` 在批量写入前临时调整 PRAGMA，写入后恢复，修改需确保恢复逻辑在异常时也能执行
- `_base_adapter.py` 提取了两种适配器的公共逻辑（连接管理、PRAGMA 操作），子类只需实现差异部分
- `RawSQLiteAdapter.clear_table()` 会清理 `sqlite_sequence` 表重置 AUTOINCREMENT 计数
- `SQLiteUtilsAdapter` 的批量插入对 None 行使用 `item or {}` 替换
- `PragmaOptimizer.restore()` 对 `str` 类型的 PRAGMA 值做正则校验 `^[a-zA-Z0-9_-]+$`

### Testing Requirements

```bash
pytest tests/test_database/
```

### Common Patterns

- 双适配器策略：`RawSQLiteAdapter`（零依赖兜底）和 `SQLiteUtilsAdapter`（功能丰富）
- `PragmaOptimizer` 使用上下文管理器模式，确保 PRAGMA 设置在异常时也能恢复
- SQL 安全：所有标识符拼接通过 `sql_safe` 模块处理

## Dependencies

### Internal

- `_utils`（logger, sql_safe, schema_helpers）

### External

- 可选：`sqlite-utils>=3.36`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
