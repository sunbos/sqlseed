# 数据库适配层

本目录提供 `DatabaseAdapter` protocol、SQLite/PostgreSQL adapter、dialect、type normalization 与批量优化。不得导入 `sqlseed.core`；通过 adapter metadata 向上层供给 schema 信息。

## 修改入口

| 工作 | 入口 |
| --- | --- |
| adapter API 与 metadata dataclasses | [_protocol.py](_protocol.py)：`DatabaseAdapter`、`ColumnInfo`、`ForeignKeyInfo`、`IndexInfo`、`CheckConstraintInfo` |
| 生产连接、查询、写入 | [sqlalchemy_adapter.py](sqlalchemy_adapter.py)：`SQLAlchemyAdapter`、`SQLAlchemyBatchInserter` |
| 原生 SQLite 测试 | [raw_sqlite_adapter.py](raw_sqlite_adapter.py)、[_base_adapter.py](_base_adapter.py) |
| dialect 与类型归一化 | [_dialect.py](_dialect.py)、[_type_normalizer.py](_type_normalizer.py) |
| SQLite AUTOINCREMENT、rowid 别名与表名识别 | [_sqlite_schema.py](_sqlite_schema.py) |
| 完整 UNIQUE 键的候选比较 | [_unique_keys.py](_unique_keys.py)：SQLite index 项的 collation，partial/expression index 不推导无条件键 |
| 批量设置管理 | [_bulk_optimizer.py](_bulk_optimizer.py)、[optimizer.py](optimizer.py)、[_helpers.py](_helpers.py) |

## adapter 合约

- 生产路径统一用 `SQLAlchemyAdapter`；`RawSQLiteAdapter`/`BaseRawSQLiteAdapter` 只用于原生 SQLite 测试。新 adapter 满足 runtime-checkable `DatabaseAdapter` 与 context manager 合约。
- 支持范围为 SQLite 与 PostgreSQL；不要附带恢复未验证的 MySQL 分支。
- 未指定 driver 的 `postgresql://` 在创建 engine 时选择 `postgresql+psycopg`，与 `sqlseed[postgres]` 的 psycopg3 依赖一致；保留显式 driver、原始连接目标与配置 URL，不增加协议别名。
- `ForeignKeyInfo.constraint_id` 保留表内 FK 分组身份，`ref_schema` 保留反射出的父 schema；二者默认 `None` 兼容旧构造调用。PostgreSQL reflection 使用 `postgresql_ignore_search_path=True`，防止 search_path 隐藏跨 schema 引用。元数据可读取，但 core 生成预检拒绝 PostgreSQL composite FK、显式 schema FK 与三列及以上 composite FK。
- 表操作先 `validate_table_name()`，identifier 使用 `quote_identifier()` 或现有 dialect quoting；值走参数绑定。
- `ColumnInfo.is_rowid_alias` 与显式 `is_autoincrement` 分开：SQLite 用真实 PRAGMA PK 索引识别，不能把所有 INTEGER PK 当 rowid；nullable 也不能把普通 SQLite PK 一概判为非空。默认 `None` 兼容旧 metadata 构造，adapter 返回明确 bool。
- `IndexInfo.is_partial` 默认 `False`；反射 WHERE 索引必须标记为 `True`，不得通过 `get_unique_constraints()` 补成无条件 UNIQUE。`predicate` 默认 `None`，生产 SQLAlchemy adapter 保留条件原文；RawSQLite 只保留标记、条件原文可未知。谓词由数据库执行。
- SQLite 表名按 ASCII 大小写规则解析到 catalog 名称（含 FK 父表），禁止 Unicode casefold 或套用到 PostgreSQL。
- PostgreSQL 仅 ASCII 大小写不同的列名（如 `"A"` / `a`）可读取，但当前 CHECK 推断无法区分，生成/preview/config 在任何表清空或写入前必须明确拒绝。
- 数据库专有行为放在 `Dialect`；native type 经 `TypeNormalizer` 归一化，避免把方言细节传给 mapper。
- `SQLAlchemyAdapter` 捕获 `sqlalchemy.exc.*`。`PragmaOptimizer`/原生 SQLite helpers 中捕获 `sqlite3.*` 是有意的边界差异。
- 插入计数为目标表实际接受的行数：SQLite 使用非负 affected-row count；PostgreSQL 用 `RETURNING 1` 汇总分页结果。不把 trigger 忽略行、trigger 额外写入或驱动未知 `-1` 当作成功插入数。
- `batch_insert()` 消费 iterator，以单次调用为事务范围：本次调用中所有内部 batches 一起 commit/rollback。多次调用不自动形成一个事务。
- `SQLAlchemyAdapter.transaction()` 是显式、当前仅验证 SQLite 的跨调用事务：以 `BEGIN IMMEDIATE` 开始，读查询、reflection、raw cursor、批次写入、self-FK UPDATE 与清空共享同一 connection，外层退出才 commit/rollback。禁止嵌套与作用域内 close；暂停 bulk PRAGMA 优化并在 finally 恢复。默认无此上下文时保持单次 batch_insert 的提交语义；不能以 SQLite 回归声称 PostgreSQL 此能力可用。
- 修改 raw cursor 生命周期时检查调用方是否还要 `fetchall/fetchone`；不要在返回 cursor 前关闭它依赖的连接。
- 无参数的 `execute()` 调用 DBAPI 时不传空参数 tuple；psycopg 会把空 tuple 视为绑定模式并误解析合法 SQL `%`。非空参数仍交给驱动绑定，不能自行插值。

## 批量优化

- 沿用 `apply_bulk_optimize()` / `apply_bulk_restore()`，设置变更必须 preserve → optimize → restore 成对处理。
- SQLite 用 PRAGMA；PostgreSQL 用 session settings。恢复放在调用方 `finally` 中，不能只覆盖成功路径。
- PostgreSQL 连接可能回到 pool；即便 session 最终会关闭，也要恢复原设置，避免污染后续调用。
- PostgreSQL 大批量优化不能自动切换 `session_replication_role=replica`：必须保留 FK 与用户 trigger，预计行数不改变数据完整性语义。
- SQLite PRAGMA 与 autoincrement 检测留在对应 helper；不把原生 SQLite 行为当作所有 dialect 的默认值。

## 验证

命令从仓库根执行。

- `pytest tests/test_database/`：真实 SQLite、adapter contract、rollback、URL 与安全边界。
- adapter API 或 metadata 变化补跑 `pytest tests/test_orchestrator_adapter.py tests/test_schema.py tests/test_relation.py`。
- PostgreSQL 相关改动使用 `make test-integration`（需要 Docker），不要只凭 SQLite 通过认定跨数据库行为正确。
- `lint-imports` 验证本层没有反向依赖核心。
