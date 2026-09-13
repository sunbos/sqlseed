# test_database

本目录验证 adapter Protocol、SQLAlchemy/RawSQLite 行为、dialect、SQL 安全与 PRAGMA；实现规则见 [database/AGENTS.md](../../src/sqlseed/database/AGENTS.md)。

## 入口与本地约束

- `conftest.py` 提供 `sa_adapter`（基于 tmp_db）与 `empty_sa_adapter`（空 SQLite），以及受影响行数场景的 `counts_database`、原子事务场景的 `transaction_database`；后两者共享 schema 建立与 adapter 关闭的上下文，并由 yield fixture 管理清理。全局 `tmp_db` / `raw_adapter` 来自仓库根 fixture。
- `test_adapter_contract.py` 与 `test_sqlalchemy_adapter.py` 验证真实 adapter 契约；`test_raw_sqlite_adapter.py` 保留测试 adapter 的行为。
- `test_sqlalchemy_adapter_boundary.py` / `test_sqlalchemy_adapter_url.py` 覆盖错误路径与 URL 模式。SQLite URL 测试不需要 Docker，真实 PostgreSQL 用例位于 `tests/integration/`。
- `test_helpers.py` 覆盖索引查询、采样和 batch insert；用真实 SQLite 校验实际数据库结果。
- `test_dialect.py` / `test_sqlite_schema.py` 覆盖类型归一化、自增检测与 identifier quoting；不要把 PostgreSQL 行为当作 SQLite 通用规则。
- `test_sqlite_metadata_oracles.py` 用原生 INSERT 建立 rowid、nullable 和 partial UNIQUE 的独立 oracle，再核对两种 adapter；仅比较索引名称或同模型构造的 expected 会漏掉谓词丢失。
- `test_insert_actual_count.py` / `test_sqlalchemy_transaction.py` 验证实际受影响行数与原子事务；`test_typed_value_bindings.py` / `test_sqlite_date_bindings.py` 验证真实绑定结果，不能只比较传给 driver 的值。
- `test_unique_key_probes.py` / `test_supported_schema_boundary.py` / `test_ascii_schema_tokens.py` 覆盖键值查询与支持边界，须保留写入前拒绝不支持结构的回归。
- `test_optimizer.py` 必须覆盖 PRAGMA 正常恢复与异常恢复；连接资源必须清理。
- `test_sql_safe.py` 保留多种注入向量与引用边界；测试 SQL 名称处理时不能只验证函数调用。
- 不 mock 数据库正确性路径；模拟缺失 driver 等外部失败时，限制 mock 到现有错误边界，实际连接/写入仍用真实库测试。

## 验证

从仓库根执行：

```bash
pytest tests/test_database/
pytest tests/test_orchestrator_adapter.py
```

跨 dialect 修改追加 `pytest tests/integration/test_pg_*.py tests/integration/test_url_e2e.py`。独立测试库与 Docker fallback 的选择见 [integration/AGENTS.md](../integration/AGENTS.md)。
