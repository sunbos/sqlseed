# sqlseed-web 包边界

本包是本机 Web 工作台：FastAPI 包装离线 core 与可选 AI 能力，直接提供静态 ES modules。正式导航为工作台、配置管理、运行记录、设置；连接使用同主题弹窗。当前产品能力见 [Web 工作台指南](../../docs/web-workbench.md)。

## 入口与局部指南

| 范围 | 入口与规则 |
|---|---|
| HTTP API、连接、持久化与后台任务 | [后端指南](src/sqlseed_web/AGENTS.md) |
| 页面、规则面板、状态与样式 | [前端指南](src/sqlseed_web/static/AGENTS.md) |
| 包依赖、extra 与 console script | [pyproject.toml](pyproject.toml) |
| API、Node 与安装验收 | [测试指南](tests/AGENTS.md) |

## 包与产品约定

- 本包是 standalone app，不注册到 `project.entry-points."sqlseed"`。必需依赖为 Core、FastAPI、Uvicorn、PyYAML、packaging；准确版本范围以 manifest 为准。
- 当前源码要求 Core `>=0.2.5.dev0,<0.3`，共享连接解析和诊断脱敏不能与旧 Core 混装；AI extra 仍为 `>=0.2.4.dev0,<0.3`。不能为安装方便放宽已使用接口的版本下界。`[ai]` 安装可选 AI，`[dev]` 提供 pytest/httpx。
- 没有 npm/Vite/bundler 或前端构建步骤，静态资源随 Python wheel 分发。保持一套清透玻璃设计及其浅色/深色模式与现有工作台交互；历史 connect/wizard/browse/heal/meta 页面不在正式 router 中加载，兼容旧 API 不要求恢复旧导航。
- 正式界面提供简体中文与 English，UI 偏好独立于生成配置的 locale。切语言只更新显式绑定的展示内容，不重挂页面、不发业务请求、不改用户数据；JS 字典和后端消息 JSON 同随 wheel 分发。维护入口见 [Web 双语维护](../../docs/development/web-i18n.md)，不得把开发实现说明写成已完成发行/浏览器验收。
- 外观入口位于正式设置及组件样板页头；支持浅色、深色、跟随系统，默认浅色。偏好仅存当前浏览器并同步同源标签页，跟随系统自动响应明暗变化；不修改 AI 设置或生成配置，不发起 AI 或业务请求。主题及字体约束见前端指南。
- 未安装 AI 时基础连接、schema、配置、预览和填充仍可用。AI 仅按用户请求提供待审阅建议，应用后进入同一配置，不在写入时隐式调用 AI。provider/locale 属于生成配置，不属于连接表单。
- `sqlseed-web` 与 `python -m sqlseed_web` 默认启动 supervisor 和可替换 worker，监听 `127.0.0.1:8630`；安装发行包后即可启动，不需要仓库脚本。直接托管 `app:create_app` 可使用业务，但不具备自动组件管理。
- 草稿和运行保存在用户应用数据目录的 `sqlseed/workspace.sqlite3`，可用 `SQLSEED_WEB_WORKSPACE_PATH` 覆盖。连接凭据不随配置持久化；AI 普通设置、进程内密钥及 endpoint 隔离规则见后端指南。
- 默认受管模式在支持的独立环境中提供网页内组件管理；部署能力由后端返回，不能因为环境不可管理而阻止普通 Web。旧 `--manage-plugins` 只作兼容入口，不是普通启动步骤。
- 历史设计计划与原型用于解释已有决策；修改时以当前实现、正式指南和局部回归约束核验，不将旧导航、历史测试数量或阶段性验收状态当作新增需求。

## 验证

完整开发依赖使用 [根指南](../../AGENTS.md) 的五包安装命令。从仓库根运行：

```bash
pytest plugins/sqlseed-web/tests/ -q
node --test plugins/sqlseed-web/tests/test_*.cjs
ruff check plugins/sqlseed-web/
mypy plugins/sqlseed-web/src/
```

根 pytest 包含 Web，CI 单独运行 Node 内置测试，无 npm 依赖。页面行为修改需补实际浏览器验证；真实 LLM、PostgreSQL、安装后入口验收分别记录，不能互相替代。generator/hook 元数据从 core 动态读取，不将历史数量硬编码为新事实。
