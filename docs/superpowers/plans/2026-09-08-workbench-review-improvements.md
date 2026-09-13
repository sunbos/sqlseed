# Workbench Review Improvements Implementation Plan

> **For agentic workers:** 使用 subagent-driven-development 分配独立职责；主代理负责整合与验收。保留现有未提交改动，不执行提交／推送。

**Goal:** 落实评审 R1–R6，让复杂数据库下的定位、依赖阅读与字段授权更清楚，并验证数据库目标身份。

**Architecture:** 保留 model/session 和后端执行契约。主页面负责布局与依赖呈现，graph/AI 模块独立改进，SQLite 身份采用同一精确规则并保留普通路径旧 key；旧 URI 采用显式导入。

**Tech Stack:** 原生 ES modules、CSS、Node 内置测试、Python/FastAPI/SQLAlchemy、pytest、真实浏览器及 Figma。

## 工作与检查清单

- [x] 阅读现状截图、REVIEW、COVERAGE 和沿途 AGENTS；核对设计依据并写入 [实施规格](../specs/2026-09-08-workbench-review-improvements.md)。
- [x] R1/R3：修改 `plugins/sqlseed-web/src/sqlseed_web/static/js/pages/workbench.js` 的 draw/drawSidebar，将设置与配置工具合并，表名与状态分行；在 `static/workbench.css` 修改现有组件规则。视觉改动不写镜像式 CSS 测试，使用浏览器测量重叠、横向溢出、内容起点与点击范围。
- [x] R6：先在 `plugins/sqlseed-web/tests/test_workbench_context.cjs` 加依赖顺序回归：构造 38 条来源和错误／提醒，断言错误先于来源，来源可展开，生成入口禁用，定位不改选择。运行该文件确认失败，再修改 `renderDependencies()` 的呈现顺序与状态。
- [x] R2：graph.js 保留布局计算，新增实际缩放说明、读当前路径与搜索定位；在 `test_workbench_graph.cjs` 验证实际比例、完整路径、未改选择和搜索 veto。相关 CSS 由主代理统一整合。
- [x] R5：ai.js/ai.css 提供字段搜索与明确授权动作。`test_workbench_ai.cjs` 检验完整请求 `allowed_targets`、隐藏选择、生成文档不变、忙碌／关闭保护。
- [x] R4：先真实 SQLite 红测试；规范目标身份，保留普通路径旧 key，禁止有歧义的 legacy alias 授权。Python schema/runtime/store 与 JS session 严格使用 canonical key；不同目标仍拒绝。新增归属及兼容回归，保留不可变运行快照。
- [x] 整合后运行 `node --test plugins/sqlseed-web/tests/test_*.cjs`、`pytest plugins/sqlseed-web/tests/ -q`、`ruff check plugins/sqlseed-web/`、`ruff format --check plugins/sqlseed-web/`、`mypy plugins/sqlseed-web/src/`。失败按变更范围调查，不以历史失败跳过新回归。
- [x] 真实浏览器走查 1144×872 与窄视口：长表定位、宽表滚动、依赖问题首屏、整库与路径阅读、仅指定字段授权、当前表／已选表预览、无效输入和连续点击。生成/失败/回滚沿用临时 SQLite 验收，不写用户库。
- [x] 同步 `docs/web-workbench.md`、相关 AGENTS，移除“100%是适应画布”的旧说明；新建阶段二记录与 Figma 对照，保留阶段一不变。
- [x] 核对最终差异、原业务库与配置未改变，给出已完成项、验证证据及仍未执行的真实 AI／PostgreSQL 状态。

## 独立职责

主代理：workbench.js、workbench.css、上下文回归、文档及浏览器/Figma。图子任务：graph.js/graph-layout.js与图测试；AI子任务：ai.js/ai.css及AI前端测试；身份子任务：Python后端、session.js与对应测试。共享 CSS、主页面和用户浏览器由主代理独占操作。

## 验收结果

2026-09-08 完成实现、回归和浏览器走查。最终范围、数据核对及服务生效说明见 [阶段二验收记录](../../design-review/2026-09-08-improvements/README.md)。前端 424 项、Web Python 271 项通过；真实 AI／PostgreSQL 未执行。运行／失败／回滚由真实临时 SQLite 回归验证，本轮没有额外制作浏览器写入结果截图。原 8630 服务会话保留，Python 改动下次重启加载。
