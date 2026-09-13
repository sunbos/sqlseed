# Preview Editing and Database Data View Implementation Plan

> 使用 subagent-driven-development 按职责并行实施；用户已批准评审方案和最新导航/引擎表述。保留当前未提交工作区，不提交或推送。

**Goal:** 从预览直接调整字段规则/AI 建议，在运行完成后查看数据库当前数据，并统一导航及环境说明。

**Architecture:** Core 和真实依赖保持不变。Web 新增有限分页只读接口与共享数据面板；运行记录按目标身份核验连接。预览复用原字段/AI 编辑流程，保留返回上下文与失效保护。环境命令按当前服务解释器与可用 pip/uv 生成，仅展示指引。

**Tech Stack:** FastAPI、SQLAlchemy、原生 JS/CSS、pytest、Node test、Playwright。

## 1. 设置与导航

Owner：settings_metadata_review。文件：settings_environment.py、pages/settings.js、settings.css、index.html、对应设置与 shell 测试。

- [x] 先增加安装指引选择 pip/uv/无工具的行为回归，确认失败，再实现针对服务解释器的命令；不执行安装/卸载。
- [x] Base 显示内置；Faker 显示随 sqlseed 安装；Mimesis 显示按需安装。保留后端 requirement 事实，移除环境文案“动态读取”。
- [x] 设置三个操作按钮采用一致纯文字尺寸；导航固定为工作台、运行记录、配置管理、设置。
- [x] 运行 settings、shell Node 测试与 test_web_settings.py，报告新鲜结果。

## 2. 预览就地编辑

Owner：graph_semantics_review。文件：workbench/preview.js、pages/workbench.js、局部 preview CSS、必要 AI/editor 回调、对应预览集成测试。

- [x] 先增加列元数据/依赖排序/实际预览表定位/返回上下文回归，确认失败。
- [x] 两行表头显示列名与类型/关键约束；选列显示字段信息、调整规则和 AI 操作，使用原 editor 与 openAI 预检。
- [x] 表标签优先使用响应 order，保留未排序已选表；不改变 document.tables 或生成范围。
- [x] 批量预览与抽屉/AI 明确往返，保留表、行数、滚动；应用规则后旧样例明确失效，取消不改规则，迟到响应不污染新视图。
- [x] 列级 AI 显式使用预览 shownTable 与选列；只读结构保持不变，不自动调用 AI。
- [x] 跑相关 Node 测试，报告完成后 root 集成工作台数据入口。

## 3. 正式只读数据接口

Owner：preview_stability。新建 workbench_data.py 与 test_workbench_data.py，app.py 注册 router。不改变旧 rows API。

- [x] 真实临时 SQLite 回归：分页、复合主键排序、空表列信息、无主键说明、输入范围、忙碌、错误表与运行目标不匹配；先确认新路由失败。
- [x] GET `/api/workbench/connections/{conn_id}/tables/{table}/data`，limit 1–100、offset 非负、可选 run_id。使用连接操作门禁；run_id 存在时对照真实 target_key 与运行表授权。
- [x] 返回 table/target_key/target_label/dialect/columns/rows/total/limit/offset/order_by/read_at，无主键时明确未指定稳定顺序。使用真实 schema 的主键/列；SQL 标识符引用并兼容 SQLite/PostgreSQL；错误脱敏。
- [x] GET `/runs/{run_id}/data-connections` 从已注册连接中匹配目标，前端消费候选，分页接口再次独立核验；连接失效不可按脱敏地址自动重连。
- [x] 跑新增与相关 Python 测试，ruff/format/mypy。

## 4. 共享数据查看面板

Owner：root。新建 workbench/table-data.js、局部 CSS 与 test_table_data.cjs；修改 runs.js，最后集成 workbench.js。

- [x] 先写面板行为测试：加载实际记录、空表表头、分页/刷新、完整值可选取、错误重试、关闭与迟到响应、运行目标匹配。
- [x] 面板明确“数据库当前数据”，显示目标/表/读取时间，使用接口分页；状态/旧结果保留，切页和刷新不改变业务数据或配置。
- [x] runs 逐表增加“查看当前数据”，仅选择匹配运行目标的连接；无连接时说明先连接相同数据库。支持部分失败结果，不能标为本次新增。
- [x] 工作台“已有 N 行”旁复用入口，保持当前表编辑与勾选状态。

## 5. 集成与验收

- [x] 代理交叉只读复核，root 核对所有接口、返回上下文与边界。
- [x] Web Python/Node 全套，Ruff/format、mypy、import-linter、architecture/doc-sync、git diff --check。
- [x] 独立临时服务/SQLite 在桌面和手机尺寸实测预览选列、规则/AI 往返、分页与运行目标、安装指引。AI 流程验证界面和范围，不擅自调用模型。
- [x] 保存截图和更新指南、验收文档；确认空闲后更新正式 Web，保留用户当前模型和已有连接。

验收记录：[第一版验收](../../design-review/2026-09-10-preview-data-v1/README.md)。
