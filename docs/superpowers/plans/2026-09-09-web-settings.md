# Web Settings Implementation Plan

> 使用并行子任务按文件职责实施；保留用户现有未提交变更，不执行提交或发布。

**Goal:** 建立独立应用设置页，精简 AI 助手并稳定预览刷新布局。

**Architecture:** 仅在 Web 插件新增设置存储与环境元数据、原生 ES module 页面；core 与 AI 推理接口保持独立。现有 AI 配置接口保留兼容，检测支持不保存的表单快照。

**Tech Stack:** FastAPI、Pydantic、Python 标准库、原生 JavaScript/CSS、pytest、Node test。

## 1. 设置后端

- [x] 对 `test_web_settings.py` 增加临时文件重启恢复、密钥不落盘、跨地址不复用、检测不保存、安装状态与写入失败测试，先确认失败。
- [x] 在 Web 内提供独立设置存储、`GET /api/settings/environment`；扩展 `workbench_ai.py` 配置来源和草稿检测，接入 `app.py`。
- [x] 运行 `pytest plugins/sqlseed-web/tests/test_web_settings.py -q`，核验响应和真实持久文件。

## 2. 独立设置页

- [x] 新增 `test_settings.cjs`，执行真实页面模块，验证首次读取、编辑检测无保存、保存密钥清空、检测过期、迟到响应和缺插件。
- [x] 新增 `static/js/pages/settings.js`、`static/settings.css`；`app.js` 和 `index.html` 注册设置入口。
- [x] `POST /test` 提交 `JSON.stringify({backend, model, base_url, api_key, clear_api_key})`，只有保存按钮调用 `POST /config`。读取有效设置时 password input 始终为空。
- [x] 运行 `node --test plugins/sqlseed-web/tests/test_settings.cjs plugins/sqlseed-web/tests/test_app_shell.cjs`。

## 3. AI 助手往返

- [x] 在既有 AI 交互测试增加设置入口、无凭据输入、范围/业务说明恢复、过期模型拒绝恢复。
- [x] 精简 `workbench/ai.js`，通过内存 handoff 与 `pages/workbench.js` 往返，不把分析草稿放 URL/localStorage。
- [x] 运行 `node --test plugins/sqlseed-web/tests/test_workbench_ai*.cjs`。

## 4. 预览刷新

- [x] `test_workbench_preview.cjs` 用可控 Promise 验证旧 DOM 保留与滚动恢复，先红后绿。
- [x] 修改 `preview.js`，新增 `preview.css` 并由唯一 style.css 引入。
- [x] 运行对应测试与浏览器延迟请求下的尺寸检查。

## 5. 集成与文档

- [x] 更新 Web 局部 AGENTS 与 `docs/web-workbench.md`，同步主导航、持久化和凭据说明。
- [x] 运行 Web Python/Node 全套、ruff/mypy 和架构检查。
- [x] 独立服务与临时工作区浏览器验收设置页面、AI 往返、预览稳定性；真实模型调用与用户数据库写入不属于此次验收。

## 验收结果

2026-09-10 完成；见 [设置与预览验收记录](../../design-review/2026-09-10-settings/acceptance.md)。
