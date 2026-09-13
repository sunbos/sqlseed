# integration

本目录覆盖真实 PostgreSQL、URL API 与真实 LLM。共享 fixtures 位于仓库根 [conftest.py](../../conftest.py)，通用测试规则见 [../AGENTS.md](../AGENTS.md)。

## 入口与运行依赖

- `test_pg_integration.py`：PostgreSQL adapter、schema、fill 与 FK；`test_url_e2e.py`：通过 public API/CLI 验证 URL 模式。
- 未设置 `PG_TEST_URL` 时，`pg_url` fixture 用 testcontainers 启动 `postgres:16-alpine`，把连接 scheme 调整成 `postgresql+psycopg`；需要 Docker daemon、testcontainers 和 psycopg。
- `pg_url` 优先读取 `PG_TEST_URL`（CI 提供的独立测试数据库），此时不启动或停止 Docker；未提供时创建并清理自己的临时容器。不要将该变量指向业务数据库，集成用例会建表与写入测试数据。
- PostgreSQL 回归还包括 `test_pg_typed_value_bindings.py`（JSON/时间值往返）、`test_pg_insert_actual_count.py`（触发器与实际行数）、`test_pg_bulk_integrity.py`（FK/触发器及设置恢复）、`test_pg_case_sensitive_schema.py`（写入前识别列名冲突）和 `test_pg_driver_selection.py`（URL driver 选择）。跨数据库修改不能只运行最早的 integration 文件。
- `test_ai_real_llm.py` 通过 `available_llm_backend` 探测 Ollama、LM Studio、Google AI Studio，验证 analyzer、refiner、streaming、hook 与 CLI 的真实路径。该 fixture 的探测顺序不代表生产 `AIConfig` 的自动 fallback 策略。
- 复用 `tests/_helpers.py` 的 `configure_llm_backend_env`，用 monkeypatch 隔离 backend 环境；不把 API key 或实际连接凭据写入仓库。
- 服务不可用时沿用 fixtures 的 skip/fail 判定；不要把真实服务替换成 mock 后继续把用例称为 integration。

## 收集与验证

从仓库根运行：

```bash
pytest tests/integration/test_pg_*.py tests/integration/test_url_e2e.py -v --tb=short
pytest tests/integration/test_ai_real_llm.py -v
make test-integration
```

- 新增测试模块显式声明 `pytestmark = pytest.mark.integration`，不要依赖 `conftest.py` 中的同名变量向子模块传播。
- 已观察到 `test_ai_real_llm.py` 没有模块级 marker；其 docstring 声称 conftest 自动标记，实际需以 pytest 收集结果为准。要完整运行这里的用例，按目录/文件执行，不仅用 `-m integration`。
- 修改 streaming/refiner 时保留配置状态隔离、normal → compact → ultra-compact 降级与不可重试错误的真实回归。
- 报告外部服务缺失导致的 skip，与实际执行通过的测试区分开。
