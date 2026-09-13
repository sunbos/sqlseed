# Settings and Graph Clarity Implementation Plan

> 用户已确认上一轮逐项评审，使用 subagent-driven-development 按文件职责并行实施，保留当前工作区，不提交或发布。

**Goal:** 解释保存状态、组件依赖与环境来源，让关系图的状态和当前依赖链清晰可辨。

**Architecture:** 改动限 Web。环境接口补充稳定的分类/依赖/安装说明，版本继续从当前 Python 获取；AI 缺失与导入异常分开。设置前端消费这些事实并呈现状态。图中选择仅改变视觉强调，保留生成选择、路径范围、布局、缩放和检查语义。

**Tech Stack:** FastAPI、importlib.metadata、原生 JS/CSS/SVG、pytest、Node test、浏览器实测。

## 1. 组件与 AI 状态（后端）

文件：`settings_environment.py`、`workbench_ai.py`、`tests/test_web_settings.py`。

- [x] 增加缺包与已安装但导入失败的回归，保证提示不泄露异常或凭据。
- [x] 环境条目加入 category（application/extension/provider）、requirement（required/optional/builtin）、dependency_ids、安装指引；Core/Web 当前应用，AI/CLI/MCP 扩展，AI 明确依赖 CLI。
- [x] 保留动态版本；Base 前端显示随 Core 提供。Faker 缺失属于必需依赖异常，Mimesis 未安装为可选状态。
- [x] 运行 `.venv/bin/pytest plugins/sqlseed-web/tests/test_web_settings.py -q`。

## 2. 设置页反馈与布局（前端）

文件：`static/js/pages/settings.js`、`static/settings.css`、`tests/test_settings.cjs`。

- [x] 状态回归：Key 为空且修改模型可保存；无更改显示原因；服务切换更新认证提示；导入失败不显示尚未安装。
- [x] 将保存反馈与连通性信息分开；无修改显示“没有待保存的更改”，不假称有效环境配置已写盘。
- [x] 插件按当前应用/可选扩展/生成引擎分组；内置/必需/可选与安装状态分别显示。未安装条目有安装指引，已安装失败有修复指引。
- [x] 左侧导航增加随内容收缩的浅底细框；说明当前 Web 运行环境及配置路径动态来源。
- [x] 运行 `node --test plugins/sqlseed-web/tests/test_settings.cjs`。

## 3. 关系图语义（独立前端）

文件：`static/js/workbench/graph.js`、新增 `static/graph-clarity.css`、`tests/test_workbench_graph.cjs`。

- [x] 回归覆盖显示图例、状态文字、当前选择外圈、关联链强调和无关线淡化；选择不重排布局、不改变生成范围；环/分叉可终止。
- [x] 图例解释本次生成/仅引用/其他表与当前查看，现有 node role/keyboard 语义保留并补状态。
- [x] 静态高亮当前表上下游相关链，单边选择优先级更高。问题色保留可读；不添加持续动画。
- [x] 运行 `node --test plugins/sqlseed-web/tests/test_workbench_graph.cjs`。

## 4. 写入目标说明

文件：`static/js/pages/workbench.js`、必要的局部 CSS 与对应测试。

- [x] 确认弹窗为当前 schema.target_label 添加“写入目标”、数据库类型，完整路径/脱敏 URL 可选取复制；不更改目标推导或支持范围。
- [x] 回归核验 SQLite/PostgreSQL 展示及正确目标，不能输出凭据或暗示 MySQL 支持。

## 5. 集成验收

- [x] 在 style.css 挂载图形专用样式，独立复核代理改动与接口字段匹配。
- [x] Web Python/Node 全套，Web ruff/format、mypy、架构/文档检查。
- [x] 用独立临时 SQLite 验证设置无修改/空 Key 编辑、缺插件/加载异常、图例/链路高亮和手机布局；不调用 AI 或向用户数据库写入。
- [x] 更新文档与验收截图；保留当前模型与连接后更新正式服务供用户查看。

验收结果与截图见 [2026-09-10 设置与关系图记录](../../design-review/2026-09-10-clarity/acceptance.md)。
