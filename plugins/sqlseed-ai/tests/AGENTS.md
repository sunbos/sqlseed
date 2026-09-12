# sqlseed-ai 测试

继承 [插件规则](../AGENTS.md)。从仓库根执行 `pytest plugins/sqlseed-ai/tests/`；本包测试与 Core 测试分开存放。

## 测试布局与依赖

- `test_ai_*` 覆盖配置、client、analyzer、hooks 与 CLI；`test_contracts_*` / `test_validator_*` / `test_repair_*` 对应 Layer 1–3。
- `test_healer_*` 覆盖确定性降级、subgraph、diff learning、broken-edge 对齐；[healer/](healer/) 同时有纯逻辑测试和 `*_real.py` 的真实 LLM 测试。
- [test_auto_heal_orchestrator.py](test_auto_heal_orchestrator.py) 保存 CHECK Pattern 和 Step 5.5 回归；新增同类案例优先归入这里。
- [property/test_matrix_completeness.py](property/test_matrix_completeness.py) 使用 Hypothesis 与内存 SQLite；`hypothesis` 来自本包 `[dev]` extra，不是 Core 的运行时依赖。
- 新增依赖插件可选安装的测试入口使用 `pytest.importorskip("sqlseed_ai")`，或沿用所在文件已有的 module-level ImportError skip；不要伪造缺失依赖。

## Fixtures 与断言

- `tmp_db`、`unique_test_db`、`pg_url`、`available_llm_backend` 等由根 [conftest.py](../../../conftest.py) 自动发现；不要再通过 `pytest_plugins` 重复注册。
- 本地 [conftest.py](conftest.py) 用 importlib 读取根 [tests/conftest.py](../../../tests/conftest.py) 的 helper，并提供 `mediator_ctx`（真实 RawSQLiteAdapter + SchemaInferrer）。helper 复用与 fixture 发现是两种机制。
- [schema_helpers.py](schema_helpers.py) 共享真实 SQLite schema 的创建与 snapshot；`timestamp_snapshot` 由本地 conftest 提供。`healer/scenario_helpers.py` 仅共享固定产品 CHECK 场景，不替换真实 LLM 调用或断言。
- 可选性只在 `sqlseed_ai` 顶层检查；顶层导入成功后，内部模块加载失败必须报错，不能用子模块 `importorskip` 掩盖破损安装。
- 数据库与 schema 使用 `tmp_path` / 内存 SQLite，保持真实 mapper / adapter 计算；不得 mock 数据库层。检查生成配置、错误分类或实际行值，而不只检查调用次数。
- `RepairExecutor` 的拒绝修复案例必须同时验证配置不变、无 `applied_fixes`、原 violation 进入 `unfixable`；参考 [test_repair_executor.py](test_repair_executor.py)。
- CHECK 回归覆盖优先级、组合上下界、NULL、负数、列顺序、DATE / DATETIME 和 LIKE 文本；phone 精确长度要同时覆盖初始推断与 Layer 3 repair。
- CLI 测试用 `click.testing.CliRunner`，不要 subprocess；配置测试隔离环境变量，可复用根 [tests/_helpers.py](../../../tests/_helpers.py) 的 LLM env helpers。

## 真实 LLM 与验证命令

- [healer/conftest.py](healer/conftest.py) 的 `llm_client` 检查 LM Studio；服务不可用时 skip。模型可用 `SQLSEED_TEST_LLM_MODEL` 指定。
- 保持 healer `*_real.py` 的真实 LLM 合同：使用真实环境或 skip，不能用 mock LLM 伪装通过。该限制针对真实 LLM 测试，不把其中用于隔离调度的 deterministic validator stub 当作真实修复证据。
- 部分集成测试通过根 `available_llm_backend` / `pg_url` 使用真实后端或 PostgreSQL；报告结果时区分 pass 与因环境缺失而 skip。
- 局部验证可从下列命令选择；按修改面补上对应的 validator / CLI / healer 文件：

```bash
pytest plugins/sqlseed-ai/tests/test_ai_config.py plugins/sqlseed-ai/tests/test_ai_tool_calling.py
pytest plugins/sqlseed-ai/tests/test_contracts_matrix.py plugins/sqlseed-ai/tests/test_repair_executor.py plugins/sqlseed-ai/tests/test_repair_pipeline.py
pytest plugins/sqlseed-ai/tests/test_auto_heal_orchestrator.py plugins/sqlseed-ai/tests/test_cli_auto_heal.py
```

测试不在 mypy strict 范围，仍需通过 Ruff；不要用放宽断言、吞异常或模拟生产计算来消除失败。
