# TEST SUITE

**核验日期：** 2026-09-05

## 范围与入口

本目录覆盖 core API、编排与各内部模块；`test_hardware.py`、`test_refiner.py` 等仍有 AI 插件相关回归。新增插件测试放各插件自己的 `tests/`，不要仅凭文件名假定其依赖属于 core。

| 任务 | 入口 |
|---|---|
| Public API、连接互斥 | `test_public_api.py`、`test_url_connection.py` |
| 编排与 adapter 集成 | `test_orchestrator.py`、`test_orchestrator_adapter.py` |
| 映射、schema、FK | `test_mapper.py`、`test_mapper_camelcase.py`、`test_schema.py`、`test_relation.py` |
| Core 算法、CHECK、unique | [test_core/AGENTS.md](test_core/AGENTS.md) |
| 配置、snapshot | [test_config/AGENTS.md](test_config/AGENTS.md) |
| Adapter、dialect、SQL 安全 | [test_database/AGENTS.md](test_database/AGENTS.md) |
| Provider、dispatch、media | [test_generators/AGENTS.md](test_generators/AGENTS.md) |
| pluggy 与 manager | [test_plugins/AGENTS.md](test_plugins/AGENTS.md) |
| 日志、metrics、paths、progress | [test_utils/AGENTS.md](test_utils/AGENTS.md) |
| 真实 PostgreSQL / LLM | [integration/AGENTS.md](integration/AGENTS.md) |
| 性能测量 | [benchmarks/AGENTS.md](benchmarks/AGENTS.md) |

## Fixtures 与隔离

- 共享 fixtures 定义在仓库根 [conftest.py](../conftest.py)，pytest 对 core 和插件自动发现；本目录 [conftest.py](conftest.py) 只保留可导入的 helper functions。
- `tmp_db_simple` 是单表库；`tmp_db_full` / `tmp_db` 是 users/orders 外键库；`tmp_db_with_data` 预置用户数据；`unique_test_db` 提供 projects 与唯一索引。
- `raw_adapter` / `raw_adapter_with_data` 是测试专用 adapter fixtures；`pg_url` 与 `available_llm_backend` 是 session fixtures，需要外部服务。
- 构造 schema 使用 `make_column_info()`、`create_simple_db()`、`create_project_info_db()`；enrichment 可用 `apply_enrichment()`。新测试不用已弃用的 `make_col()`。
- 用 `tmp_path` 创建真实 SQLite，不 mock 数据库层；连接、orchestrator 用 context manager 或 fixture teardown 释放。`gc_between_tests` 是 opt-in，不要改成 autouse。
- 原生 `sqlite3.Connection` 的 context manager 只负责提交/回滚，不关闭连接。测试通过 `from tests.sqlite_helpers import sqlite_connection` 使用 `with sqlite_connection(...) as conn:`，统一提交/回滚与关闭；它保留 `sqlite3.connect` 的连接参数，提交失败也会关闭。只需读取且不需要事务的连接可单独使用 `closing()`；连接 fixture 使用 `yield` 加 teardown，不直接返回未托管连接。
- 纯 core 测试可使用 `provider="base"` / `provider_name="base"` 获得可重复占位数据；provider 真实性、locale 与 dispatch 回归必须使用对应 Faker/Mimesis provider，不能一律替换成 base。
- CLI 使用 `click.testing.CliRunner`，不启动 subprocess；AI 可选依赖用 `pytest.importorskip("sqlseed_ai")` 或现有模块级 skip 模式。
- 普通测试沿用 `test_<module>.py`；mypy 不检查 tests，但保留清楚的类型注解。断言实际输出，不只断言 mock 被调用，具体例子见 `test_core/AGENTS.md`。
- 同时要求集合类型与空值的输出契约使用 `tests.assertions.assert_empty(actual, list/dict/tuple)`；helper 只接收一次实际计算结果，并拒绝 `None`、`False` 和错误集合类型。只关心真假时仍直接使用 `assert not value`。

## 验证

从仓库根运行：

```bash
pytest tests/test_orchestrator.py
pytest tests/test_core/
pytest tests/test_architecture.py tests/test_doc_sync.py
pytest plugins/sqlseed-web/tests/
```

- 根 `pyproject.toml` 的默认 `pytest` 包含 tests、CLI、AI、MCP、Web；`make test-core` 不包含本目录根层用例。
- `test_architecture.py` 校验 import 边界、public API、production isolation 与注册集合；配合 `lint-imports` 使用。
- `test_package_boundaries.py` 对整个源目录执行 AST 导入检查：离线 core 不直接导入插件或模型 SDK，Web/MCP 不导入 AI CLI，AI runtime 不依赖终端入口。此检查不依赖测试进程此前已经加载哪些模块，不覆盖任意动态导入。
- `test_doc_sync.py` 检查源码事实与 Markdown 标记；它的 AGENTS 路径列表是显式的，新增文件并不自动加入该列表。`scripts/sync_docs.py --check` 会扫描 Markdown 标记。
- 真实服务用例与 benchmark 的执行、跳过条件及收集差异见各自本地指引；不要把 skip 或未收集报告成验证通过。
