<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# test_database

## Purpose

数据库适配层测试。覆盖双适配器功能、PRAGMA 优化和 SQL 安全。

## Key Files

| File | Description |
|------|-------------|
| `test_raw_sqlite_adapter.py` | RawSQLiteAdapter 功能测试 |
| `test_sqlite_utils_adapter.py` | SQLiteUtilsAdapter 功能测试 |
| `test_optimizer.py` | PragmaOptimizer PRAGMA 优化测试 |
| `test_sql_safe.py` | SQL 注入防护测试 |

## For AI Agents

### Working In This Directory

- 适配器测试需要真实 SQLite 数据库，使用 `tmp_db` fixture
- SQL 安全测试需覆盖各种注入攻击向量
- 优化器测试需验证 PRAGMA 设置的保存（preserve）与恢复（restore）逻辑

### Testing Requirements

```bash
pytest tests/test_database/
```

### Common Patterns

- Raw 适配器测试使用全局 `conftest.py` 中的 `tmp_db` / `raw_adapter` fixture
- SQLiteUtils 适配器测试使用模块内局部 fixture（`_sqlite_test_db` / `_adapter`）直接实例化适配器
- 优化器测试通过注入 `execute_fn` / `fetch_fn` 验证 PRAGMA，无需真实数据库

## Dependencies

### Internal

- `src/sqlseed/database/`

### External

- `pytest>=8.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
