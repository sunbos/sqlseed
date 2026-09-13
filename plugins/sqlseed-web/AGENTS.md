# sqlseed-web 包边界

本包是本机 Web 工作台：FastAPI 包装 core 与可选 AI 能力，直接提供静态 ES modules。
产品 shell 与 presentation 已按确认的 v8 完成整体重建，主导航为工作台、运行记录、配置管理和设置，连接使用同主题弹窗。[可用性与 AI 辅助计划](../../docs/superpowers/plans/2026-09-07-workbench-usability-ai.md) 是后续细化与当前实施状态的依据；[v8 重建契约](../../docs/superpowers/plans/2026-09-07-web-v8-rebuild.md) 保留样式基线及历史核验事实。本轮浏览器、真实 LLM 与 PostgreSQL 验收应分别记录，不能以历史测试推定完成。

规范顺序：2026-09-07 标准化实施计划与功能层级方案 → 当前可用性与 AI 辅助计划 → v8 重建契约 → v8 原型 README/HTML → 重设计提案中未被后续评审覆盖的业务规则。后续细化保留 v8 单一主题；用户在标准化评审中批准配置管理作为第三项导航。旧连接、向导、浏览、配置助手、系统信息页面为保护未提交改动物理保留，不能由正式 router 加载，也不作为新 UI 基线。旧 HTTP API 的兼容与后端约束不要求保留旧导航或样式。

## 入口与局部指南

| 范围 | 入口与规则 |
| --- | --- |
| HTTP API、连接与后台任务 | [src/sqlseed_web/AGENTS.md](src/sqlseed_web/AGENTS.md) |
| 页面、属性面板与样式 | [static/AGENTS.md](src/sqlseed_web/static/AGENTS.md) |
| 包配置与 console script | [pyproject.toml](pyproject.toml) |
| API 与前端回归 | [tests/AGENTS.md](tests/AGENTS.md) |

## 包与运行约定

- 本包是 standalone app，不注册到 `project.entry-points."sqlseed"`。
- 必需依赖为 `sqlseed>=0.2.4.dev0,<0.3`、FastAPI、Uvicorn、PyYAML、packaging；Core 0.2.3 缺少工作台所需 runtime 接口，不能放宽此下界。`[ai]` extra 安装 `sqlseed-ai`，`[dev]` 提供 pytest/httpx。
- 没有 npm/Vite/bundler 或前端构建步骤；静态资源随 Python wheel 一起提供。
- 全部运行页面、连接空状态与弹窗共享 v8 主题；provider/locale 属于生成配置，不属于连接表单的产品设置。
- 保持未安装 AI 时基础连接、schema、配置、预览和填充仍可用；工作台新增可选 AI 辅助分析面板，建议先审阅后应用，不能恢复旧 heal 导航或在写入时自动调用 AI。AI 导入与缺失依赖响应见后端指南。
- `sqlseed-web` 与 `python -m sqlseed_web` 默认启动稳定 supervisor 与可替换 worker，监听 `127.0.0.1:8630`；直接托管 `app:create_app` 仍可使用业务，但不具备自动组件管理。
- 正式工作台、可选 AI 辅助与使用边界见 [Web 工作台指南](../../docs/web-workbench.md)。草稿和运行存入用户应用数据目录的 `sqlseed/workspace.sqlite3`，可用 `SQLSEED_WEB_WORKSPACE_PATH` 覆盖；连接凭据不随配置持久化。

## 测试与验证

从仓库根执行：

```bash
python -m pip install -e "." -e "./plugins/sqlseed-web[dev]"
pytest plugins/sqlseed-web/tests/ -q
node --test plugins/sqlseed-web/tests/test_*.cjs
ruff check plugins/sqlseed-web/
mypy plugins/sqlseed-web/src/
```

- 根 pytest `testpaths` 包含 web，CI setup-env 安装本包；Node 内置测试运行器在 CI lint job 中运行，无 npm 依赖。
- 使用 FastAPI `TestClient` 和临时真实 SQLite；`client` fixture 会关闭残留连接，因为 module-level `state` 跨 app factory/TestClient 存活。
- AI 专项测试使用 `pytest.importorskip("sqlseed_ai")`；连通性测试只替换 HTTP 边界，不替换数据库层。
- generator/hook 元数据从 core 动态读取；修改对应接口时检查 `TestMeta`，不要把历史数量硬编码为新事实。
- 前端回归加载真实 JS 模块，DOM/network 边界由测试 helper 提供；页面变更还需在浏览器验证涉及的控件、导航和配置往返。

## 2026-09-09 应用设置评审

- 用户已批准第四项主导航“设置”，由新 `pages/settings.js` 提供 AI 服务、插件与版本；不恢复旧 meta/heal 页面。普通设置由 Web 的 `ai_settings.py` 持久化，密钥保持环境变量或进程内存且按服务绑定。新环境接口由 `settings_environment.py` 只读汇总当前 Python 环境。
- 工作台 AI 助手仅展示服务/模型摘要与设置入口；范围、业务说明、分析和审阅继续留在助手。`ai-handoff.js` 只在内存保存明确往返的上下文，身份/epoch/schema/生命周期失效时拒绝恢复。设置检测草稿不保存，不以模型列表成功声称推理成功；保存/检测防重复，迟到响应不覆盖新页面。
- AI 普通设置字段为 backend/model/base_url；`SQLSEED_WEB_SETTINGS_PATH` 可覆盖。UI key 不入磁盘，不随跨 endpoint 切换继承，清除只在当前进程有效。配置表单不把同一进程中的设置称为浏览器私有。
- `preview.js` 重新预览保留上次 DOM、选中表和滚动；状态标明旧结果，失败保留旧结果。`preview.css` 只提供首载占位和状态高度。使用当前行为回归与实际浏览器尺寸核验，不能把历史测试数当成本轮验收。

## 2026-09-10 预览编辑与当前数据

- 预览表头使用真实列元数据；就地编辑复用字段规则抽屉与同一 AI 助手，显式绑定 shownTable/column。取消保持配置，应用标记旧样例失效。批量标签按 result.order 且保留错误表。预览→AI→设置显式返回通过内存 handoff 携带预览上下文，沿用身份/epoch/schema/lifecycle 守卫，不持久化样例。
- `workbench/table-data.js` 是工作台与运行记录共享的只读分页面板。运行结果只承诺“数据库当前数据”，不伪称本次新增快照；运行入口按目标匹配连接，后端再次验证。关闭、切运行或离页后丢弃迟到响应。
- 安装指引来自后端针对服务解释器生成的 pip/uv 命令，缺工具明确说明；引擎设置跳转插件页复用指引，不另拼 pip 命令。Faker 仍为 Core 必需依赖，UI 标签为“随 sqlseed 安装”。
