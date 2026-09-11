# sqlseed Web v8 整体重建 Implementation Plan

> **For agentic workers:** 按 subagent-driven-development 或 executing-plans 分工执行；使用下面的 checkbox 记录经验证的进度。用户已批准 v8，并要求以它整体重建正式 Web；无需再次申请设计确认。本次不提交、不推送，保留已有未提交文件。

**Goal:** 将用户已对齐的 v8 视觉和交互完整实现为正式 Web，接入已有真实连接、配置、检查、生成和运行记录能力。

**Architecture:** 复用 FastAPI 后端、完整配置模型、session 与图布局计算；重新建立产品 shell、页面结构、样式和规则抽屉。正式 router 只加载工作台和运行记录，连接通过同主题弹窗进入；旧页面因已有未提交改动物理保留，但不再是可加载路由或设计基线。

**Tech Stack:** Python 3.10+、FastAPI、SQLAlchemy、Pydantic、SQLite 工作台存储；原生 ES modules、DOM、CSS；pytest 与 Node 内置测试。静态资源继续随 Python wheel 分发，无新增前端构建依赖。

## 当前设计契约

状态：2026-09-07 整体重建已实现并完成本轮自动检查及实际浏览器检查；待用户复核新版效果。前次功能测试不作为本轮视觉证据。

规范顺序：**本契约 → [v8 原型 README](../prototypes/sqlseed-workbench/README.md) 与 [index.html](../prototypes/sqlseed-workbench/index.html) → [重设计提案](../specs/2026-09-06-sqlseed-web-redesign-proposal.md) 中未被后续评审覆盖的业务规则**。旧 AGENTS、向导计划和截图分类不能逆向覆盖当前契约。

### 产品结构与交互

- 主导航仅“工作台 / 运行记录”。首次未连接时显示同主题空状态和连接按钮；新建、切换连接在弹窗完成，不建立独立连接页。系统信息、配置助手、数据浏览与旧三步向导不进入正式 router。
- 沿用 v8 叶芽与表格组成的 SVG logo、sqlseed 字标、字体、色彩、空间节奏与控件层次。重建整个 shell 和 presentation，不能保留旧控制台外壳后只更换工作台内容。
- 点左侧表名和行数区域固定打开字段规则；右侧节点分支图标固定打开完整依赖路径；点数据库名称打开整库图，信息按钮只显示连接事实。复选框独立决定生成范围。
- 配置顶栏管理同一份文档：配置文档、依赖检查、生成摘要、刷新整组样例；真实保存、打开配置和配置级 provider/locale 在同一配置上下文内补齐。数据库工具栏位于表标题上方，管理整库结构名称、数量和导入/导出；表标题旁放行数与加入生成；字段规则使用共用的右侧抽屉。
- 字段、图旁详情、规则抽屉与 YAML/JSON 文档共享同一配置。打开其他表、图搜索、定位和结构导入不改变写入范围。未选表的规则草稿可保留；无效输入不能静默保存最近有效旧值。
- 依赖检查只有一套面板，顶栏、侧栏待处理数量与摘要均定位到它。摘要中的顺序可定位图节点并同步左表高亮；保持面板，定位不改变数量、规则或勾选。
- 全局生成引擎和语言地区属于生成配置；连接只负责数据库目标和连接事实。无 AI 也必须完成完整流程，本轮不新增 AI 导航或调用。
- 首次连接、空状态、保存/打开、运行记录、错误和所有弹窗使用同一主题。只有一套生效的 tokens 与组件样式，不以旧 Material 3 和新工作台双主题叠加实现。

### v8 视觉事实

以下数值取自原型根样式；具体控件和响应式覆盖以原型对应规则为准，不能用“相似绿色”或旧布局近似代替。

| 项目 | 基准 |
|---|---|
| 色彩 | canvas `#eef3f5`、paper `#fff`、ink `#193441`、muted `#617682`、line `#dce5e9`、navy `#234e61`、teal `#167765`、soft `#eaf5ef`、violet `#6958a4` |
| 字体 | 正文 `14px/1.55 "PingFang SC", "Microsoft YaHei", sans-serif`；标识/样例 `ui-monospace, SFMono-Regular, Consolas, monospace` |
| 品牌与顶栏 | 原型 SVG logo，27×27；字标 23px、weight 720；顶栏高 67px、左右 30px、品牌/导航间隔 52px |
| 页面 | max-width 1500px，基础 padding `27px 30px 25px`；标题 27px；配置标题区下间距 25px |
| 工作区 | 基础侧栏 211px、主区 `minmax(0,1fr)`，圆角 12px；表标题 padding `24px 27px 20px`，字段/工具按同一 27px 对齐线 |
| 控件 | 基础按钮 min-height 35px、padding `7px 13px`、圆角 7px；主操作用 teal；图标基准 18px、stroke-width 1.6；右侧抽屉 `width:min(390px,100%)`、padding 29px |
| 表格 | 字段、规则、三条完整样例并列；默认列宽 22% / 30% / 每条样例 16%，样例纵向对应同一记录 |
| 响应式 | 以原型 1380px、1000px、760px 断点及后续覆盖为准；窄屏保留必要导航与操作的可达性，不机械复制演示用禁用/隐藏 |

验收统一覆盖 **1144×816、1144×872、1440×900**：前两种尺寸分别来自早期提案和最终原型记录，都保留为回归视口。图缩放“100%”表示适应画布，“放大阅读”恢复原始阅读字号。

### 数据与历史模块边界

复用已有 `workbench_schema.py`、`workbench_store.py`、`workbench_runtime.py`、`workbench.py`。保留真实 grouped FK、配置完整性、revision/hash、凭据脱敏、preview 不写库、服务端多表任务、失败停止、实际部分提交量和重启 interrupted 语义。不得为了迁移视觉改回逐表浏览器托管任务或模拟样例。

`pages/connect.js`、`wizard.js`、`browse.js`、`heal.js`、`meta.js` 与旧 `genform.js` 可以保留文件及历史测试；正式 router 不动态导入这些页面，未知/旧 hash 回到当前工作台。它们的面板顺序、连接级 locale、分类占位与样式不约束新工作台。

原型的固定 5/24 表、15 种演示 generator、来源存在/缺少按钮与“未接入”记录入口不是生产内容。正式 schema、目录、样例和来源事实来自后端；连接、记录与保存的新增视图沿用 v8 设计语言。

## 文件职责与实施步骤

### 1. 产品 shell 与单一主题

**Files:** 修改 `plugins/sqlseed-web/src/sqlseed_web/static/index.html`、`static/js/app.js`、`static/style.css`、`static/workbench.css`；新增 `plugins/sqlseed-web/tests/test_app_shell.cjs`。

- [x] 先增加真实 shell/router 回归：主导航仅两项、默认工作台、旧 hash 不加载旧页面、离页调用 unmount；在旧实现上确认失败原因。
- [x] 从 v8 迁移 SVG 品牌、顶栏、页面容器与基础 tokens。`index.html` 仅加载 `style.css`；`style.css` 先 `@import workbench.css` 再承载 v8 全量基础规则。`workbench.css` 仅定义组件新类名，不含 tokens、body 或旧 Material 3 覆盖。
- [x] router 使用明确的工作台/运行记录映射，保留迟到响应检查；旧路径安全回到工作台。
- [x] 运行 `node --test plugins/sqlseed-web/tests/test_app_shell.cjs`，检查两页、空状态与弹窗均使用新 shell。

### 2. 首次连接与切换

**Files:** 新增 `plugins/sqlseed-web/src/sqlseed_web/static/js/workbench/connection.js`、`plugins/sqlseed-web/tests/test_app_shell.cjs`；修改 `static/js/app.js`、`static/js/api.js` 的集成入口。

- [x] 先覆盖首次无连接、恢复有效连接、失效连接、关闭弹窗后的迟到响应与取消不切换目标。
- [x] 实现同主题连接弹窗与空状态：SQLite 路径/服务器文件选择、PostgreSQL URL、连接状态与就近错误；复用已有连接 API。
- [x] 连接成功后载入真实 schema，切换时保护当前文档身份和未保存状态；provider/locale 由配置编辑，连接表单不把它们作为产品级设置。
- [x] 运行 `node --test plugins/sqlseed-web/tests/test_app_shell.cjs` 并验证错误不会污染当前配置。

### 3. 工作台与右侧规则抽屉

**Files:** 修改 `static/js/pages/workbench.js`、`static/js/workbench/editor.js`、`graph.js`、`ui.js`、`static/workbench.css`；复用 `model.js`、`session.js`、`graph-layout.js`、`dependency-view.js`；新增 `tests/test_workbench_v8.cjs`，迁移 `test_workbench_page.cjs` 仍适用的行为，并验证 `test_workbench_editor.cjs`、`test_workbench_graph.cjs`。此处 `static/`、`tests/` 分别相对 Web source 与 Web package。

- [x] 先覆盖固定表/图入口、库级工具在两视图可用、共享右抽屉、配置顶栏作用范围、IME/光标及依赖定位状态；确认旧 presentation 的偏差会失败。
- [x] 按 v8 重建侧栏、字段与三条样例、结构工具栏、表数量、关系图和集中依赖面板；接入真实目录与样例。
- [x] 规则编辑器从右侧进入；切字段、取消与应用后恢复合理焦点。旧 inline auto-apply 不再是正确预期；迁移测试时保留其有效状态约束。保存/打开与配置文档只操作同一模型；无效草稿保留但不可运行。
- [x] 复用现有版本保护和图计算；对确需变化的集成契约更新调用者，不重新创造配置状态。
- [x] 运行 `node --test plugins/sqlseed-web/tests/test_workbench_*.cjs`，确保浏览与编辑均不隐式扩大写入范围。

### 4. 运行记录与完整流程

**Files:** 修改 `static/js/pages/runs.js` 与共享 presentation；验证 `tests/test_runs.cjs`、`tests/test_workbench_acceptance.py`。

- [x] 记录列表、详情、空状态和错误沿用同一主题；展示固定版本、逐表状态、已提交量和不确定计数。
- [x] 运行真实临时 SQLite HTTP 流程：连接→修改→保存→重开→检查/预览且行数不变→父子计划执行→记录与实际 JOIN 一致。
- [x] 核对离页不取消后台运行、网络错误不冒充失败；不新增取消、续跑、整库事务或 AI 能力承诺。

### 5. 文档与验收收敛

**Files:** Web 各层 `AGENTS.md`、`docs/web-workbench.md`、中英文 README、下列历史文档状态说明。

- [x] 更新规范优先级和旧模块适用范围；使用指南只描述新导航与连接弹窗，不保留六页旧流程。
- [x] 运行下面的自动验证；逐项记录本轮结果，不能搬用上次测试数量充当本次完成证据。
- [x] 检查静态资源、import、wheel 和 CSS token/布局对照。浏览器权限限制仍在时明确视觉、鼠标、键盘验证未完成；不换浏览器或用其他地址绕过。
- [x] 负责人根据实际结果更新完成状态；未完成视觉验收保持单独列出，不声称 v8 视觉验收已通过。

## 验证命令

从仓库根执行；以下为需运行的检查，不是已通过记录。

```bash
node --test plugins/sqlseed-web/tests/test_*.cjs
node --test docs/superpowers/prototypes/sqlseed-workbench/*.test.cjs
.venv/bin/python -m pytest plugins/sqlseed-web/tests/ tests/test_core/test_generation_partial.py tests/test_architecture.py tests/test_doc_sync.py -q
.venv/bin/ruff check plugins/sqlseed-web/
.venv/bin/ruff format --check plugins/sqlseed-web/
.venv/bin/mypy plugins/sqlseed-web/src/
.venv/bin/lint-imports
.venv/bin/python scripts/sync_docs.py --check
git diff --check
uv build --wheel --out-dir /tmp/sqlseed-web-v8-wheel plugins/sqlseed-web
```

Node/DOM、CSS 对照、资源可达性和 HTTP 测试分别证明对应边界，不能代替真实浏览器的视觉、滚动、焦点、鼠标与键盘检查。真实 PostgreSQL 也须单列环境验收。

## 历史规范处置

| 文档 | 当前作用 |
|---|---|
| 根 `implementation_plan.md` | 整体 superseded；旧向导与旧控制台增量重排，不再执行 |
| `web_capability_alignment.md` | 历史能力盘点；旧 IA/P0/P1 清单 superseded |
| `generator_parity.md`、`generator_ui_reference.md` | 截图/能力差距资料；连接级 locale、照搬分类、空分类占位不生效 |
| `2026-09-05-sqlseed-web-functional-fixes.md` | 已完成的旧 UI 修复记录；数据库与并发回归经验保留 |
| `2026-09-07-workbench-production.md` | 前次后端/API/状态模型接入记录；旧 shell 增量接入方式 superseded |
| `2026-09-07-workbench-verification.md` | 前次功能测试证据；不表示 v8 视觉/整体设计已验收 |
| 重设计提案第 3、19、20、21、22 节 | 按演进保留历史；当前导航与固定入口由本契约和 v8 决定 |

已验证的后端能力无需因重新设计 UI 被废弃；尚未支持的执行能力仍由后端明确报错，完整配置保存/导出不得静默删字段。

## 本轮核验记录（2026-09-07）

- 正式 Web Node 回归：187 passed。涵盖两项导航/入口依赖闭包、连接弹窗、规则抽屉事务、迟到请求、配置下载保真、导入结构隔离、图状态与运行记录。
- Python：Web + architecture/doc-sync 共165 passed；已提交批次计数回归另1 passed（总166）。测试使用临时 SQLite，不向用户数据库写入。
- 原型103项回归通过；ruff check / format、mypy、import-linter、文档同步、diff whitespace检查通过。sync_docs仍提示CLAUDE示例marker-name未知，标记值本身已同步。
- wheel构建成功；当前正式入口的动态ES模块全部可达、保持no-cache并包含于wheel。
- 实际浏览器已可访问当前正式服务。检查了工作台字段/真实预览、完整路径图/字段标签、从图打开规则抽屉、连接弹窗、记录空态；确认使用统一v8视觉而非旧控制台。检查默认1144×872、1144×816、1440×900与760px窄屏，已恢复默认视口；1144×816下完整路径及字段标签在适应画布100%时完整可见。未提交用户数据库生成任务，浏览器未记录warn/error。
- 真实PostgreSQL执行环境尚未额外验收；本轮未改变后端执行契约。AI仍未接入。
- 旧页面源文件及其回归保留为历史，正式router不可加载；不删除本轮前已存在的用户未提交改动。
