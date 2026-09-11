# 可维护版本与订单演示 Implementation Plan

> **For agentic workers:** 使用 subagent-driven-development，按独立文件职责执行并在集成时审查需求与代码质量。

**Goal:** 交付一个支持边界诚实、订单案例可复现、AI 入口不依赖 CLI 私有实现的个人可维护版本，并提供可核验的演示与简历素材。

**Architecture:** 保留离线 core、现有 public API 和五个 package。AI 模型构造与编排构造进入 AI 插件内的非交互服务模块；CLI/Web 仅做适配。不引入业务 DSL、编排框架、微服务或跨表聚合承诺。

**Tech Stack:** 现有 Python、SQLAlchemy、Pydantic、pytest、ruff、mypy、Node 测试运行器。

用户已确认上一轮的三项实施范围。本轮在当前含历史改动的工作区继续，基线快照在 `/var/folders/cl/xphppvtj3qx0n89rkx8tzyd80000gn/T/sqlseed-maintainable-u2y82zgd`。保留现有变更，不自动提交、合并、发布，不修改用户业务数据库。

## 1. 数据库支持与执行结果

**Files:** `src/sqlseed/core/relation.py`、`src/sqlseed/core/orchestrator/_generation.py`、`src/sqlseed/core/result.py`、`src/sqlseed/database/sqlalchemy_adapter.py`（以复现定位的最小文件集合为准）；`tests/test_core/test_supported_execution_contract.py`、`tests/test_database/test_supported_schema_boundary.py`。

- [x] 读取目录指引与现有两列复合 FK、部分提交、取消回归，确认实际行为。
- [x] 用真实临时 SQLite 复现三列以上复合 FK 未协调抽样的边界；断言在生成/清空前明确失败且旧数据不变。PostgreSQL 不具备完整分组/namespace 信息时，保留可检测的结构并拒绝不受支持的组合，不伪装为普通 FK。
- [x] 使用真实分批插入测试成功、第二批失败、协作取消，断言实际记录数与结果一致；如已有行为正确则保留并引用现有测试。
- [x] 对确定性缺口做最小修复，不扩展到完整 n 列/跨 schema 支持，不掩盖现有已支持行为。
- [x] 运行 `.venv/bin/pytest tests/test_core/test_supported_execution_contract.py tests/test_database/test_supported_schema_boundary.py` 和受影响现有测试。

## 2. AI 服务边界

**Files:** `plugins/sqlseed-ai/src/sqlseed_ai/runtime.py`、`plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py`、`plugins/sqlseed-web/src/sqlseed_web/api.py`；`plugins/sqlseed-ai/tests/test_runtime.py` 及对应 Web 兼容回归。

- [x] 核对 `_build_ai_config`、`_build_llm_client`、`_build_heal_orchestrator` 的参数、异常、资源所有权和现有消费者。
- [x] 先加入口回归：非 CLI 服务导入/调用不依赖 Click，不调用 `SystemExit`；可选依赖失败有普通异常；同一配置选择同一现有模型客户端/编排器。
- [x] 提取实际共享构造逻辑到 `runtime.py`，保持现有默认编排算法与后端，CLI 负责终端错误转换；Web 改用服务模块。必要的兼容包装留在 CLI，外部消费者不再引用它。
- [x] 保留已存在的进度与错误协议；核对失败能向调用者传播，避免新增另一条分析流程或真实收费模型调用。
- [x] 运行 `.venv/bin/pytest plugins/sqlseed-ai/tests/test_runtime.py plugins/sqlseed-web/tests/test_api_regressions.py` 及影响到的 AI 回归。

## 3. 可复现订单示例

**Files:** `examples/order_workflow/`（schema、规则、运行脚本、说明）；`tests/test_order_workflow.py`。先检查已有 `examples/scenario_lab/` 并复用经验，避免把其压力库冒充本次完整可写入案例。

- [x] 定义 users、products、orders、order_items 的依赖、业务不变量与固定 seed/时间范围，不添加当前引擎不支持的跨表聚合规则。
- [x] 先写案例测试：在两个新临时目录运行，生成结果相同，FK/CHECK/UNIQUE 合法，数量正确；坏规则失败可诊断、旧行不被覆盖，修正规则后可重放。
- [x] 实现脚本调用 public Python API，保存可供 CLI/Web 使用的 YAML；示例不会覆盖已有目标数据库。
- [x] 运行 `.venv/bin/pytest tests/test_order_workflow.py` 和独立命令演示；保留机器可读验证结果与复现条件。

## 4. 维护、展示与核验

**Files:** `docs/maintainable-release.md`、`docs/project-showcase.md`、README 中简短入口、`tests/test_package_boundaries.py`（静态导入契约，补充现有 architecture 回归）。

- [x] 文档列出已验证支持、明确拒绝、尚未验证，区分 SQLite 本地证据、PostgreSQL 环境结果、固定模型回归与真实模型实测。
- [x] 定义维护边界、公开 API 兼容原则、单一默认 AI 路径和版本完成条件，明确暂缓新 DSL/大规模评测平台/重写。
- [x] 提供演示步骤、架构说明、一个故障修复案例与真实范围内的简历表达，所有指标可追溯，不编造用户量、性能、就业结果。
- [x] 审查三个实现的需求覆盖，再审查异常、资源释放和包依赖；补必要跨包边界回归。
- [x] 运行 ruff check、format check、mypy、lint-imports、可离线 Python 回归（真实 LLM 显式排除，外部环境 skip 单列）、Web Node 兼容、architecture/doc-sync。检查文档命令可执行。
- [x] 比较本轮基线文件与最终文件，记录新增/修改范围及验证证据；逐项核验后才标记目标完成。

## 完成条件

1. 订单示例真实写入、失败诊断、修正与固定条件重放均有可执行证据。
2. 已识别的不支持结构不会进入危险写入；成功/失败/取消的已提交结果与数据库相符。
3. 本轮已涉及的非 CLI AI 消费者不再导入 CLI 私有工厂，core 不受模型厂商类型影响。
4. 维护说明与项目展示能诚实说明支持和验证边界，测试与示例命令通过；历史用户改动保留。

## 最终验收

2026-09-09：上述完成条件已逐项核对。验证数字、外部环境限制及文档站遗留问题见仓库 `docs/code-review/2026-09-09-maintainable/README.md`。未提交或发布。
