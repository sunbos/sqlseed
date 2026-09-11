# sqlseed-web Functional Fixes Implementation Plan

> **历史修复记录：** 本文针对旧页面，已完成项和测试结果仅代表当时实现。当前 UI 由 [v8 整体重建契约](2026-09-07-web-v8-rebuild.md) 取代；旧向导的布局与执行限制不适用于新工作台。真实数据库约束、完整配置和并发回归经验继续保留。

> **For agentic workers:** Use subagent-driven-development for the independent file groups below. Preserve unrelated working-tree changes.

**Goal:** 修复功能审查中确认的 12 项缺陷及 auto-heal 完成发布竞态，保留现有原生 JS / FastAPI 架构。

**Architecture:** 一次生成固定连接与配置快照；向导状态与连接绑定；配置使用结构化数据保存；后端保留 Pydantic 模型字段并统一任务结束语义。修复均留在 Web 插件，Core / AI 算法不变。

**Tech Stack:** Python、FastAPI、Pydantic、真实 SQLite、pytest；原生 ES modules、Node 内置 test runner、浏览器验收。

设计依据是本任务上一轮已逐项复现的审查报告。用户已要求处理该报告，无需再次确认。直接在当前 feature checkout 修改，保留已完成但未提交的 AGENTS 更新和其他用户文件；本次不提交或合并。

## 1. API、配置和任务生命周期

Files: `plugins/sqlseed-web/src/sqlseed_web/api.py`, `state.py`, `plugins/sqlseed-web/tests/test_api_regressions.py`。

- [x] 先添加真实 SQLite 测试：CHECK 插入失败时 job 为 error 且保留 result.errors；合法配置 model_dump 往返相等；错误查询响应有 detail；driver URL 能 validate/repair；连接删除交错不留下 running；done 必须伴随 result。
- [x] 运行 `.venv/bin/python -m pytest plugins/sqlseed-web/tests/test_api_regressions.py -q` 确認失败来自原缺陷。
- [x] 实现完整 model serialization、通用 URL 判定、正确 adapter 异常边界和任务生命周期。运行中的连接删除返回可读冲突，已关闭连接任务进入明确错误；成功结果先写 result，再发布 done。
- [x] `GenerationResult.errors` 非空时保留实际行数及错误，禁止标记成功。支持前端透传 table 的 seed/batch_size/clear_before/enrich/transform。
- [x] 运行全部 Web Python 测试、ruff 与 mypy。

## 2. 向导与配置往返

Files: `plugins/sqlseed-web/src/sqlseed_web/static/js/pages/wizard.js`, `plugins/sqlseed-web/tests/test_wizard.cjs`。

- [x] 先测试 A → B 切换时所有 fill 仍请求 A；失败 job 停止后续表且没有成功提示；切库清除旧列参数和 selection。
- [x] 测试 0.5 NULL、weighted object、多源 derive_from、regex/换行及完整列配置保存不变；unique 回填；导入 table 执行参数保持。
- [x] 用结构化配置构造导出，经既有 `/api/config/serialize` 输出 YAML；保留导入的合法根/表字段。提交时复制 connId、table、columns 和参数，不跨 await 读取可变状态。
- [x] 通过 Node 回归，并与后端完整配置序列化集成验证。

## 3. 属性面板

Files: `plugins/sqlseed-web/src/sqlseed_web/static/js/genform.js`, `plugins/sqlseed-web/tests/test_genform.cjs`。

- [x] 先复现 unique 在重选列/改参数后丢失，以及 choice/bytes 切到 integer 后条件控件缺失。
- [x] 完整恢复 constraints/native/provider 等未在面板编辑的字段，保持 NULL 单位、数据库硬约束和 derived mode 互斥。
- [x] generator 改变时重建依赖其类型的面板，清理 dropdown/listeners，保留 reset 回到 zeroConfig 的约定。
- [x] Node 回归验证实际配置输出与可见控件。

## 4. 数据浏览与测试接入

Files: `plugins/sqlseed-web/src/sqlseed_web/static/js/pages/browse.js`, `api.js`（如需共享 helper），`plugins/sqlseed-web/tests/frontend_helpers.cjs`, `test_browse.cjs`, 根 pytest/CI 配置及相关 AGENTS。

- [x] 添加多连接异构表树、刷新恢复、选择连接时完整 store 更新、错误展示及乱序响应不覆盖当前选择的失败测试。
- [x] 按 connId 获取各库表，捕获异步错误，使用请求版本与 DOM 生命周期检查防止旧请求污染新页面。
- [x] 将 Web pytest 纳入默认收集/CI，使用 Node 内置 test runner 验证前端，不引入生产 npm/bundler 依赖。
- [x] 更新 AGENTS 中已经修正的旧事实及新测试命令。

## 5. 集成与复核

- [x] `.venv/bin/python -m pytest plugins/sqlseed-web/tests/ -q`。
- [x] `node --test plugins/sqlseed-web/tests/test_*.cjs`。
- [x] `.venv/bin/ruff check src/ tests/ plugins/`、`.venv/bin/ruff format --check src/ tests/ plugins/`、`.venv/bin/mypy src/sqlseed/ plugins/`、`lint-imports`（环境可用时）。
- [x] `.venv/bin/python -m pytest tests/test_architecture.py tests/test_doc_sync.py -q`、`python scripts/sync_docs.py --check`、`git diff --check`。
- [x] 浏览器临时库验收：单库生成、两库表树与刷新、unique 重选、generator 切换、失败展示；配置往返由真实 API / 前端源函数回归覆盖，复跑真实 HTTP 跨库写入案例。
- [x] 独立审查剩余缺陷与测试质量，逐项修正，再给出实际验证结果及环境限制。

## 补充复核

- [x] 预览请求与连接关闭的两个交错边界：统一返回 404，禁止重新打开已销毁 orchestrator。
- [x] 步骤内容切换时同步顶部步骤标签；刷新恢复连接后同步向导顶部目标名称。
- [x] JSON schema 对象编辑：可读 JSON、验证输入、保留有效配置并阻止无效预览；补测 weighted_choices 对象编辑。

## 最终验证（2026-09-06）

- Web 后端 64 passed（原有 43 + 新增 21），架构/文档同步 31 passed；合计 95 passed。
- Node 前端 39 passed：browse 6、genform 13、wizard 20，全部运行真实应用源函数。
- 全仓 Ruff lint / format 通过；全仓 mypy 128 source files 通过；import-linter 3 contracts kept，0 broken；JS syntax 与 git diff whitespace 检查通过。
- 默认 pytest 成功收集 2315 项，其中包含 Web 的 64 项；未将 collect-only 结果当作全仓测试执行结果。
- 本地补齐 import-linter 和 editable MCP 插件及其依赖；此前 mypy 的 6 个 untyped-decorator 错误由 MCP 依赖缺失导致，安装后消失。未修改依赖声明或 lock 文件。
- 真实 HTTP + 双 SQLite：生成过程中切换连接，最终 A.one=2、A.two=2，B.one=0、B.two=0；证据 `/tmp/sqlseed-web-cross-db-_7mq2td7/counts.json`。
- 实际浏览器 + 临时 SQLite：各连接显示自己的表，刷新后表树可用；重新选列保留 unique；choice→integer 恢复控件；单库生成 3 行且另一库为 0；CHECK 失败明确显示 0 行与停止后续表；JSON 对象正常预览，无效输入可见报错；最新标题与连接目标正确同步。
- 配置保存/加载的结构化往返通过真实 TestClient + Pydantic/YAML 和真实前端源函数验证；浏览器文件选择/下载对话框未单独验收。
- 未运行真实 LLM、PostgreSQL 或 mutation testing；本轮不合并、不提交。临时浏览器页与本轮启动的测试服务已关闭。

## 保留的执行边界

导入的根级 associations / custom_column_mappings 以及与当前连接不同的目标、provider、locale 保留在导出配置中。向导仍按当前连接和表/列参数执行，并显示相应提示；完整根级设置可用导出的配置执行。此轮未改动 core 或 AI 生成算法。

## 外键属性面板补充修复（2026-09-06）

- 用户反馈 `employees.manager_id` 显示字符串参数，而 `order_items.order_id/product_id` 不可编辑。确认 NULL 编辑会经 `fromInferred`/`buildCfg` 将外键写成 string，重选列后旧锁定判断失效。
- 向导保留完整 schema 外键关系；面板以数据库定义为依据显示引用列、自引用说明与真实预览，隐藏普通生成器及派生表达式。可空外键保留 NULL 设置，提交 `foreign_key_or_integer`，继续由 core 解析父表；不修改 core 或用户数据库。
- 保留显式 unique 与 coverage 策略；复合 PK 成员不能自动追加单列 unique。自引用空表初始化的最终 NULL 比例受既有两阶段算法影响，面板明确说明这一限制。
- 新增 7 条 Node 回归，先复现外键面板及 metadata 传递缺陷再修复；补强复合 PK 请求约束断言。浏览器独立标签验证 manager_id 修改 NULL→切列→重选仍受外键管理，order_id/product_id 引用来源与 NOT NULL 限制正确，三个字段均正常返回预览；验证标签已关闭，保留用户原有向导状态和服务。
- 补充修复后的验证：Node 46 passed（browse 6 / genform 18 / wizard 22），Web Python 64 passed；两个修改的 JS 文件语法检查及 `git diff --check` 通过。独立复核确认真实 FK 优先于派生表达式符合 core 现有行为，并用临时 SQLite 验证预览仍取父表值。
