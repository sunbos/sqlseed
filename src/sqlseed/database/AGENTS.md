# AGENTS.md — src/sqlseed/database

## 作用域

- 本目录拥有 `DatabaseAdapter` Protocol、SQLite 元数据 dataclass、两套 SQLite 适配器，以及 PRAGMA 优化器。

## 本目录规则

- 保持 `SQLiteUtilsAdapter` 与 `RawSQLiteAdapter` 的可观察行为尽量一致；如果只能改一条路径，必须明确这是兼容性差异并补对应测试。
- 表名、列名和拼接 SQL 一律经过 `validate_table_name()`、`quote_identifier()` 或 `build_insert_sql()`；不要引入新的手写 SQL 标识符拼接。
- 继续保留 `sqlite-utils` 可选依赖边界。核心包在缺失 `sqlite_utils` 时仍应能导入，并回退到原生 sqlite3 路径。
- `PragmaOptimizer` 的 preserve / optimize / restore 是成组语义。改阈值、profile 或 restore 逻辑时，同时检查 orchestrator 的 `finally` 路径。
- `_protocol.py` 里的 `ColumnInfo`、`ForeignKeyInfo`、`IndexInfo` 是上层 schema、AI、MCP 共享的数据形状；新增字段或改名会波及多个边界。
- 清表、批量插入和 `DEFAULT VALUES` 语义要兼顾空行批次与事务提交；不要只修一套适配器。

## 评审热点

- `raw_sqlite_adapter.py` 依赖 `_utils.sql_safe` 生成安全 SQL；这里的回归通常会在 `tests/test_database/test_sql_safe.py` 和集成测试一起暴露。
- `sqlite_utils_adapter.py` 需要兼容第三方库返回值形状，异常分支通常应软化成空列表或稳定错误，而不是把 AttributeError 直接抛给上层。
- `optimizer.py` 的 restore 只恢复安全的 PRAGMA 值；放宽校验前先确认不会把不可信值拼回 SQL。

## 验证

- 数据库层：`pytest tests/test_database`
- 关联集成：`pytest tests/test_orchestrator.py tests/test_schema.py tests/test_relation.py`
