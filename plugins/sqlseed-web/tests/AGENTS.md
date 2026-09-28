# sqlseed-web 回归测试

上层见 [包指南](../AGENTS.md)。从仓库根运行：

```bash
pytest plugins/sqlseed-web/tests/ -q
node --test plugins/sqlseed-web/tests/test_*.cjs
```

- 当前产品与验收基准见 [工作台指南](../../../docs/web-workbench.md) 和 [前端约束](../src/sqlseed_web/static/AGENTS.md)。旧 wizard/genform/browse 测试保留历史模块行为，不要求这些页面进入正式 router，也不能把旧 DOM 布局、inline auto-apply 或六项导航当新设计预期。
- 新 shell 回归使用 `test_app_shell.cjs`，连接弹窗使用 `test_connection.cjs`，v8 presentation 使用 `test_workbench_v8.cjs`；核对真实入口、单一主题、右抽屉与操作作用范围。旧 `test_workbench_page.cjs` 只迁移仍适用的状态与集成约束。
- 连接切换回归覆盖带 draft/run/recover/new/import 参数的工作台路由、目标连接缓存、失败/取消与迟到请求。直接异库文档必须在任何旧配置保存前被拒绝；分别验证返回当前数据库和明确选择对应数据库的恢复路径，不以移除目标校验解决路由问题。
- 自动测试与原型对照分开记录；1144×816、1144×872、1440×900 的真实视觉/滚动/键盘检查未运行时明确保留未完成，不能以历史通过数量替代。

- Python 使用 FastAPI TestClient、临时真实 SQLite，并隔离 module-level state、workspace/settings 与连接生命周期。`test_api.py` 的 client fixture 在创建前清理残留连接，不代表全套测试统一自动清理；新增 fixture 仍须在 teardown 释放自己创建的资源。AI 路由单元测试只替换外部模型边界，真实 LLM 验收单独运行。
- `test_workbench_ai.py/.cjs` 验证 schema-only 上下文、未安装/未配置、密钥不回传、参数和字段边界、分析前后结构变化、关闭/epoch/迟到响应，以及建议差异 DOM 与勾选后才应用。`test_api_ai_secrets.py` 保留旧 AI 设置兼容并禁止密钥回显；只在涉及 AIConfig 的用例中按可选依赖跳过。
- `test_workbench_ai_relations.py` 用真实 core 表达式/DAG 与临时 SQLite 验证有限关系模板、类型/NULL/循环、生成范围与列范围分离、完整未选草稿、关联分组和候选只读样例；外部模型仅在 `_call_model` 边界替换。`test_workbench_ai_integration.cjs` 验证完整请求与主工作台原子应用/异步失效，不能用 scope 扩张来简化 AI 请求。
- AI 手动微调回归须断言副本与原配置隔离、整组取消勾选及旧 evidence 失效、重新选中后的完整候选检查、校验失败保持可编辑，以及关闭/文档变化后的迟到检查不能应用；不能只断言打开了编辑器或发出了 check 请求。
- `test_generation_defaults.cjs` 与设置/工作台集成回归覆盖引擎、语言地区、生成数量、预览数量和 seed 五项偏好：边界/损坏存储、新会话与明确新建生效、已有配置/导入/运行快照不被覆盖。初始数量不能预填所有表草稿扩大 AI 范围，预览数量不进入生成文档。
- `test_workbench_guidance.cjs` 验证步骤进入真实规则编辑、单表/多表预览和确认计划，并断言无选择、无效输入与阻断问题不能跳过检查。全局 AI 入口只在顶部保留一处，字段级入口仍限定目标；侧栏检查状态不重复全局检查按钮。不能用标题或步骤高亮变化代替导航结果。
- `test_api_regressions.py` 覆盖配置完整性、DBAPI 错误、任务终态与连接关闭的并发边界；不能仅断言 mock 被调用来证明填充正确。
- Node 内置 `node:test` 不需 npm。`frontend_helpers.cjs` 提供最小 DOM 和 VM 加载器；测试执行真实应用源代码，仅替换浏览器、网络和时间边界。
- Node DOM 是局部替身，不能代替浏览器验收；触发异步 `click` / `dispatchEvent` 时需要 await。
- `test_app_shell.cjs` 对正式路由的原始 ES modules 使用原生链接器验证 import/export；DOM helper 会剥离 import，不能用其通过结果或仅检查依赖文件存在来证明浏览器能够加载模块。链接检查不执行 DOM，也不替代真实浏览器验收。
- 状态回归必须检查最终配置/请求/可见控件；并发测试用可控 Promise/Event，不依赖概率和长 sleep。
- 清空恢复回归同时验证单一重建主操作和默认折叠的追加入口、生成规则/清空状态的区别、已核对后返回的中性事实、按下游计算且先检查候选、取消和失败不改范围、确认后自动保存和重新取得计划但不提交运行。复杂夹具的五表候选应为九表；八表候选扩大为二十三表并产生循环时不得应用。覆盖连续点击、保存失败和离页后的迟到响应，不能只断言按钮存在或文案改变。
- 数量与预览回归区分每表正式数量和预览上限，验证超安全整数、非法载入/恢复、旧错误清理、无效值原样保留、修正入口实际聚焦和未选表不被勾选。图命中区和箭头回归验证独立宽度与缩放边界；光标稳定、慢速跨线与拖拽仍须真实浏览器验证。
- 批量预览编辑回归验证同规格单窗口、明确返回入口、原表/列/滚动恢复与应用后旧样例标记；内嵌预览保留抽屉。引用说明覆盖复合键、外部同名节点、无样例、取消/过期、按表展开恢复和本地切表不发请求、不改生成范围。Ctrl/Meta滚轮测试实际锚点、缩放边界、普通滚轮和销毁清理，不能只断言注册了监听。
- 新增测试文件沿用 `test_*.py` / `test_*.cjs` 命名，分别由根 pytest 和 CI Node 命令自动收集。
- `test_workbench_acceptance.py` 用临时 SQLite 跑完整 HTTP 保存→检查/预览→多表运行→持久记录，并核对实际行数。隔离 `api.state`、`workbench.state` 和 workspace 文件；不能访问用户数据库。
- `test_workbench_schema.py` / `test_workbench_runtime.py` / `test_workbench_store.py` 分别验证真实约束/目录、完整配置执行、并发版本/重启恢复；复合 FK 不拆成单列假关系。
- `complex_graph_fixture.py` / `complex_business_graph.json` 与 Python/Node 复杂图回归验证真实 schema 到图投影的契约。循环断言精确 SCC 成员与内部边，排除被阻塞下游和环间桥；组合键问题比较完整列组并保留含逗号列名。`plan` 只保留生成/引用节点以及指向生成目标的有效边，不能引入未选下游或仅引用表之间的无关边；`all` 仍保留完整结构，切换范围不得修改生成勾选。
- `test_workbench_page.cjs` 与 `test_runs.cjs` 加载实际模型/组件，使用可控 Promise 测离页、输入恢复和过期响应；不以 DOM 替身声称已完成浏览器视觉验收。

## 高风险专项入口

- `test_web_request_security.py` 校验业务同源、Host 与防嵌入；组件管理另有独立准入检查，不能用业务检查通过替代。
- 连接身份、并发与恢复测试须覆盖文件别名、URI 编码、内存库、同目标多连接、任务失败释放和跨数据库拒绝；断言实际目标与数据库内容。
- `test_workbench_target_identity.py` 联合 core 的 `test_sqlite_connection_targets.py` 验证共享 SQLite 解析器：字面 `%41` 与 `A` 是不同文件，URI 只解码一次，同目标别名共用写入门禁，不同目标仍可并行。SQLAlchemy 2.0/2.1 的兼容复验使用隔离依赖环境，不降级当前环境；本机 symlink 权限不足须明确记录，不能声称相应用例通过。
- supervisor、runtime lifecycle 与 plugin management 测试使用临时独立 virtualenv、离线测试 wheel 和有界子进程；不得在用户运行服务的环境中安装/卸载组件。Windows 文件锁传递、Job 后代清理和监听 socket 交接使用真实子进程验证；异常无法确认排空时须保持维护门禁。macOS/Linux 原有自动管理回归保留，平台跳过不能表述为跨平台实测通过。
- `test_plugin_updates.py` 保留固定来源/双哈希/metadata 校验、正反向与 extras 依赖阻断、禁止降级及保护包、执行前后环境变化、失败恢复和临时 venv 的真实 pip/uv 定向升级。网络超时用可控事件验证迟到读取无计划/磁盘/安装副作用且槽位仍占用；不能把版本查询成功当作升级成功。`test_settings_updates.py` 单独保证检查更新只读且仅接受固定组件。
- 安装后入口验收见根 `scripts/check_wheel_install.py` 和 `scripts/check_public_entrypoints.py`；源码 TestClient 成功不能证明 wheel 静态资源、console scripts 或缺少可选包时可用。
