# 工作台连续点击与组件细化验收

日期：2026-09-07。范围：连续点击卡顿，以及本轮 7 条浏览器批注。保留 v8 主题与三项主导航。

## 原因与实现

Web 直接调用 Python core，不创建 CLI 子进程。原先交互请求阻塞等待同一连接锁，短时间重复点击会占用 HTTP 工作线程；生成任务在 worker 获取锁前也缺少同库预留。连接关闭因此可能长期收到忙碌响应。另有 worker 初始化读取失败、启动失败后终态落盘失败两条路径未释放任务占用。

- 前端：工作台会话统一限制在途数据库操作，覆盖顶部、侧栏、配置文档、完整计划和结构刷新；错误释放按钮，顶部显示具体原因。可继续查看和编辑字段。结构请求共享，切页返回接续正在刷新的结果。已有会话仅在明确 `409 connection_busy` 时显示带提示的缓存结构，其他错误保留。
- 后端：交互请求不能获取连接时立即返回 409；生成任务原子预留，同库已有生成任务时拒绝新任务，独立数据库可并行。初始化、线程启动及失败落盘异常均释放占用。不自动重试写入。
- SQLite 识别规范路径、symlink、file URI 和共享内存；PostgreSQL 规范 SQLAlchemy 已知连接参数与多端点，不声称识别 DNS 别名、service 或代理后的物理数据库。

## 批注对应结果

| 批注 | 处理 |
| --- | --- |
| 数据库分配 ID 的 AI 优化 | 移除无效入口，显示保护原因；普通可编辑字段继续支持 AI，整表上下文保留 |
| 引擎特点 | 展示用途、能力边界、格式示例；说明 Base 姓名是占位值，切换中文不会变为自然中文姓名 |
| 日期及相似控件错位 | 消除旧 input margin 覆盖，输入与按钮保持同一顶部和高度；连接路径控件同步对齐 |
| 侧栏全选与表列表错位 | 统一水平内边距与控件起点 |
| 样例控件含义不清 | 明示“样例范围”、最多 3 条和“不写入数据库”，范围选择与动作独立显示 |
| 文件选择器 null | 原生 replaceChildren 不再传 null；目录列表结束无额外文本 |
| 两会话断开无效 | 显示独立断开进度及服务端忙碌原因，成功后实际从列表移除；后端不再持续堆积请求 |

## 依据

状态反馈参考 [WCAG 2.2 SC 4.1.3](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html)，使用状态区和 polite live region；按钮命名、动作语义和禁用状态参考 [WAI-ARIA APG Button Pattern](https://www.w3.org/WAI/ARIA/apg/patterns/button/)。这是对应交互的实现依据，不是整站无障碍认证。

引擎说明核对 [Faker 官方文档](https://faker.readthedocs.io/en/master/)、[Mimesis 官方文档](https://mimesis.name/master/) 及本地 BaseProvider。示例标注为格式示例，不当作实际调用结果；不宣称未经测量的性能排名。

## 验证

- Web Python：248 passed，其中本轮并发专项 25 项。
- Web Node：359 passed，覆盖双击、跨按钮并发、重绘、切页、结构刷新迟到、失败恢复、执行计划切回追加、配置解析/导出防重与 AI 保护。
- 全仓 ruff / format、mypy（135 个 source 文件）、import-linter（3 项契约）通过。architecture/doc-sync 31 passed，正式文档标记检查通过。
- `uv build plugins/sqlseed-web --wheel` 成功；wheel 含 ai-eligibility.js、provider-guide.js、date-picker.css。当前 venv 未安装 build/pip，构建使用已有 uv。
- 真实浏览器双击“查看样例”，访问日志只新增 1 次 preview 请求；按钮恢复，控制台无 error/warn。
- 临时 SQLite 经实际浏览器生成 50 行，数据库实际 COUNT=50、ID 1–50。20 个并发只读预览中 17 个返回忙碌 409，3 个在不同可用时段完成；全部在 0.256 秒内返回，预览后仍为 50 行。
- 两个临时会话断开其中一个后，页面显示 1 个会话，服务端实际移除。测试完成移除临时配置和剩余临时连接，保留运行快照用于核对。
- 日期两组 input/button 的 top 与 height 完全一致；760px 下页面 scrollWidth=745，未横向溢出；结束恢复默认窗口尺寸。
- 用户原配置 v2、Base/en_US 和两个连接已恢复。用户数据库 SHA-256 与检查前一致，本轮未清空或写入用户数据库。

真实 PostgreSQL 并发写入尚未连接验收；本轮 PG 仅完成有效连接参数的准入回归。测试、压力样例和窗口检查不代表任意数据量下的性能保证。
