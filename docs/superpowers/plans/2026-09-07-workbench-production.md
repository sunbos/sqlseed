# sqlseed v8 正式工作台接入 Implementation Plan

> **前次接入记录；UI 实施方式已 superseded。** 用户随后要求按已对齐的 v8 整体重建正式 Web，当前执行依据为 [v8 重建契约](2026-09-07-web-v8-rebuild.md)。保留本文后端/API、状态模型及功能验收事实；旧 shell 上的增量接入和下方完成项不表示本次整体设计或 v8 视觉已验收。

> **For agentic workers:** 使用 subagent-driven-development 按模块实现并交叉检查。用户已确认 v8 流程，并明确授权连接、编辑、保存、检查、生成与记录的正式接入。

**Goal:** 不启用 AI 也能完成连接数据库、编辑同一份配置、保存重开、检查预览、服务端多表生成和查询持久运行记录。

**Architecture:** 保留 FastAPI + 原生 ES modules。v8 的布局和父表到子表图方向固定；图、字段页和编辑器读取同一实时 schema，配置使用 core GeneratorConfig 的内容。Web 独立保存名称、版本和视图状态，运行时从明确选择的连接注入目标，连接凭据不落入工作台记录。

**Tech Stack:** Python 3.10+、FastAPI、SQLAlchemy、Pydantic、SQLite 工作台存储、原生 JavaScript、Node 内置测试、pytest。

## 接口与文件职责

| 文件 | 职责 |
|---|---|
| `plugins/sqlseed-web/src/sqlseed_web/workbench_schema.py` | 完整列与约束、成组外键、结构 hash、生成器参数目录 |
| `plugins/sqlseed-web/src/sqlseed_web/workbench_store.py` | 草稿乐观版本检查、固定运行快照和持久状态 |
| `plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py` | 配置规范化、确定性检查、预览、服务端顺序执行 |
| `plugins/sqlseed-web/src/sqlseed_web/workbench.py` | `/api/workbench` HTTP 契约 |
| `plugins/sqlseed-web/src/sqlseed_web/static/js/workbench/model.js` | 唯一配置状态、视图选择、异步结果版本与待保存状态 |
| `plugins/sqlseed-web/src/sqlseed_web/static/js/workbench/graph.js` | 关系图视图、筛选、缩放和定位 |
| `plugins/sqlseed-web/src/sqlseed_web/static/js/pages/workbench.js` | v8 工作台、规则编辑、导入导出、摘要与运行入口 |
| `plugins/sqlseed-web/src/sqlseed_web/static/js/pages/runs.js` | 历史和逐表运行结果 |

### Schema 与草稿契约

```js
// GET /api/workbench/connections/{conn_id}/schema
{schema_hash, target_key, target_label, dialect, provider, locale,
 tables: [{name, columns, primary_key, unique_constraints, checks,
   foreign_keys: [{id, columns, ref_table, ref_schema, ref_columns, nullable}],
   row_count, mapping}],
 nodes: [{id}], edges: [{id, source, target, sourceColumns, targetColumns, nullable}]}
// source = 父表，target = 引用它的子表。

// POST /drafts；PUT /drafts/{id} 额外传 revision。
{conn_id, name, schema_hash, document, view_state}
// document 保留完整生成配置，db_path/url 通过 conn_id 单独绑定。
// 返回 id、revision、updated_at 与保存后的内容。
```

### 检查与运行契约

```js
// POST /check 或 /preview
{conn_id, document, schema_hash, count: 3}
// 返回
{ok, schema_hash, config_hash, issues: [{severity, code, table, column, message}],
 order: [], layers: [], samples: {}, preview_complete}

// POST /runs：只接受已保存版本，服务端重新核对结构、配置和依赖。
{conn_id, draft_id, revision, schema_hash, config_hash}
// GET /runs 与 /runs/{id}：持久记录，包括各表终态和实际已提交数量。
```

## 实施步骤

- [x] 1. Schema：先写真实 SQLite 的复合外键、联合主键、CHECK、DDL hash 测试；实现一次结构索引与真实生成器目录。每次刷新重新获取结构；外部 schema 保留身份并标明执行边界。
- [x] 2. 存储：先测保存重开、版本冲突、线程并发、不可改运行快照和重启中断；使用 WAL 和短事务，默认写用户应用数据目录，测试通过 `SQLSEED_WEB_WORKSPACE_PATH` 指向临时文件。
- [x] 3. 确定性服务：先测未知字段/生成器、缺失父来源、合法父子计划、自引用、循环、过期结构、导入完整性；检查不依赖 AI、不 INSERT。预览无法取得尚未生成的真实父键时明确说明，不伪造自增 ID。
- [x] 4. 执行：先测完整参数生效、父先子后、服务端接管、失败停止、重复/过期提交、已保存版本不随后续编辑变化；按实际提交量持久更新。清空计划尚未支持时显式阻止 clear_before，禁止静默忽略。
- [x] 5. 核心计数：真实 SQLite 第二批写入失败，断言第一批已提交量保留；用小范围内部计数传递修复异常路径，不使用表总行数差冒充精确写入量。
- [x] 6. 前端模型：先测换表不改勾选、取消勾选后规则保留、配置往返、过期响应丢弃、无效输入阻止保存/执行、已保存快照不被后续修改污染。
- [x] 7. 工作台：字段规则为默认入口，右侧节点图标进完整依赖路径；数据库工具栏管结构，配置顶栏管保存/检查/摘要。接入真实样例、生成器参数、外键来源和派生规则。使用自定义 dropdown；编辑草稿保留无效输入并阻止旧值提交。
- [x] 8. 记录与导航：入口切到工作台和运行记录，旧接口/旧路由保持兼容；离开页面不取消服务端任务，返回可查询。轮询错误只显示连接问题，不冒充任务失败。
- [x] 9. 验证与文档：pytest Web + 对应 Core、Node 前端与样稿回归、ruff/mypy、架构和文档同步检查。检查 wheel 中新静态资源。更新各层 AGENTS 与使用说明。

## 验收与边界

- 真实临时 SQLite：连接 → 修改两列和行数 → 保存 → 重开 → 检查/预览（库行数不变）→ 提交父子表计划 → 查询运行与实际数据。
- 配置文件保持根级 associations/custom_column_mappings、字段 constraints/derived、table seed/batch_size/transform/enrich 等数据；未支持的运行能力必须返回具体错误，不能丢字段后继续。
- 多表运行不是整库原子事务；错误后停止未执行表，已经提交的数据保留并展示。服务重启时未完成任务标 interrupted，不能猜测最终写入数。
- AI 分析/修复、通用跨表循环回填、清空计划、取消和断点续跑不在本次能力承诺中。
- 浏览器本地文件访问持续被 URL 策略拒绝，用户已同意不继续排查；不通过 localhost 或其他浏览器绕过。自动测试与 HTML 静态检查不能替代视觉和真实键盘验收。
- 不提交或推送仓库；保留现有未提交改动。

## 完成记录

2026-09-07：前次功能接入已实现，之后的用户纠偏要求重新建立整个前端 shell 与 presentation。下列 [功能验证记录](2026-09-07-workbench-verification.md) 保留当时自动验收、构建和环境边界；本轮重建的完成状态另见当前契约。未提交或推送仓库。
