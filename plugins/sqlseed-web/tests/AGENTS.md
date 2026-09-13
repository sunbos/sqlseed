# sqlseed-web 回归测试

上层见 [包指南](../AGENTS.md)。从仓库根运行：

```bash
pytest plugins/sqlseed-web/tests/ -q
node --test plugins/sqlseed-web/tests/test_*.cjs
```

- 当前产品与验收基准见 [v8 重建契约](../../../docs/superpowers/plans/2026-09-07-web-v8-rebuild.md)。旧 wizard/genform/browse 测试保留历史模块行为，不要求这些页面进入正式 router，也不能把旧 DOM 布局、inline auto-apply 或六项导航当新设计预期。
- 新 shell 回归使用 `test_app_shell.cjs`，连接弹窗使用 `test_connection.cjs`，v8 presentation 使用 `test_workbench_v8.cjs`；核对真实入口、单一主题、右抽屉与操作作用范围。旧 `test_workbench_page.cjs` 只迁移仍适用的状态与集成约束。
- 自动测试与原型对照分开记录；1144×816、1144×872、1440×900 的真实视觉/滚动/键盘检查未运行时明确保留未完成，不能以历史通过数量替代。

- Python 使用 FastAPI TestClient、临时真实 SQLite；测试结束关闭 module-level state 中的连接。测试 AI 路由时替换外部模型边界，不调用真实 LLM。
- `test_workbench_ai.py/.cjs` 验证 schema-only 上下文、未安装/未配置、密钥不回传、参数和字段边界、分析前后结构变化、关闭/epoch/迟到响应，以及建议差异 DOM 与勾选后才应用。`test_api_ai_secrets.py` 保留旧 AI 设置兼容并禁止密钥回显；只在涉及 AIConfig 的用例中按可选依赖跳过。
- `test_workbench_ai_relations.py` 用真实 core 表达式/DAG 与临时 SQLite 验证有限关系模板、类型/NULL/循环、生成范围与列范围分离、完整未选草稿、关联分组和候选只读样例；外部模型仅在 `_call_model` 边界替换。`test_workbench_ai_integration.cjs` 验证完整请求与主工作台原子应用/异步失效，不能用 scope 扩张来简化 AI 请求。
- `test_api_regressions.py` 覆盖配置完整性、DBAPI 错误、任务终态与连接关闭的并发边界；不能仅断言 mock 被调用来证明填充正确。
- Node 内置 `node:test` 不需 npm。`frontend_helpers.cjs` 提供最小 DOM 和 VM 加载器；测试执行真实应用源代码，仅替换浏览器、网络和时间边界。
- Node DOM 是局部替身，不能代替浏览器验收；触发异步 `click` / `dispatchEvent` 时需要 await。
- `test_app_shell.cjs` 对正式路由的原始 ES modules 使用原生链接器验证 import/export；DOM helper 会剥离 import，不能用其通过结果或仅检查依赖文件存在来证明浏览器能够加载模块。链接检查不执行 DOM，也不替代真实浏览器验收。
- 状态回归必须检查最终配置/请求/可见控件；并发测试用可控 Promise/Event，不依赖概率和长 sleep。
- 新增测试文件沿用 `test_*.py` / `test_*.cjs` 命名，分别由根 pytest 和 CI Node 命令自动收集。
- `test_workbench_acceptance.py` 用临时 SQLite 跑完整 HTTP 保存→检查/预览→多表运行→持久记录，并核对实际行数。隔离 `api.state`、`workbench.state` 和 workspace 文件；不能访问用户数据库。
- `test_workbench_schema/runtime/store.py` 分别验证真实约束/目录、完整配置执行、并发版本/重启恢复；复合 FK 不拆成单列假关系。
- `test_workbench_page.cjs` 与 `test_runs.cjs` 加载实际模型/组件，使用可控 Promise 测离页、输入恢复和过期响应；不以 DOM 替身声称已完成浏览器视觉验收。
