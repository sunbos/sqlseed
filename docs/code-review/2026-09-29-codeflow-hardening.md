# 2026-09-29 CodeFlow 告警复核与边界加固

本轮基线为 `e8ecd296ac31ddb479030f3fcf52e00ae79c5aa1` 的 [CodeFlow 报告](https://app.getcodeflow.com/github/sunbos/sqlseed/commits/e8ecd296ac31ddb479030f3fcf52e00ae79c5aa1)，共 86 条告警。下表 ID 是该报告导出清单的固定编号，不是后续扫描的排序。逐项合并核对得到 **53 条修正、33 条有依据保留**，ID 1–86 无遗漏、无重复计数。

上述保留结论是第一轮审查的历史状态。9 月 30 日用户进一步要求达到零错误、零告警，剩余 33 项已继续重构；最新处置和验收范围见文末补充，不将旧扫描数字当作当前结果。

`c7524437d56967d31cde3f43f3b8b570545b316f` 的线上 CodeFlow 重扫实际报告 **0 errors、33 warnings**；已逐项核对，53 条修正项消失，33 条保留项与本记录一致。“保留”指完成具体语义审查后保留现有实现，并非尚未处理。成对重复告警可能指向同一修改，告警数量也不等于产品缺陷数量。本轮没有关闭规则、降低阈值、扩大排除范围或削弱断言。此前项目验收及 Sonar 处置仍以[项目收尾记录](2026-09-29-project-closure.md)为准，不将历史结果挪作本轮验证。

## 关联审查发现的真实缺陷

| 问题 | 修复及行为证据 |
| --- | --- |
| AI 自修复流式路径接受达到输出上限的 JSON 前缀 | `AiConfigRefiner` 流式调用显式启用严格响应检查，拒绝 `finish_reason=length`；固定 HTTP / SSE、CLI 与真实 SQLite 回归验证失败时不覆盖旧 YAML、不写数据库，原重试预算不变。此处补齐自修复路径，不改变分析器 Python API 的默认兼容模式。 |
| Tool calling 参数为合法 JSON 非对象时抛出 `AttributeError` | 数组、数字、字符串、布尔值和 `null` 在严格模式下得到安全的 `invalid_json`；兼容模式保留正文及协议回退。验证实际 SDK 解码、原始标识符与请求次数。 |
| 缓存 `_meta` / `config` 非对象导致崩溃 | 将畸形缓存按未命中处理；实际模型响应经过既有目标与生成规则验证后才替换缓存。测试使用临时缓存及真实 SQLite，不把错误对象强行转换成配置。 |
| Web 组件临时目录清理失败后任务永远停在运行中 | 清理抛出 `OSError` 时仍发布脱敏的 `failed` 终态。普通清理失败与安装器尚未确认退出分开：后者继续持有环境锁和维护门禁，不能提前恢复服务。真实 Windows 文件共享锁及可控清理失败覆盖普通 / supervised、安装返回码 0 / 17。 |
| 版本查询的 socket 超时未限制 DNS / 响应头等待总时长 | 固定 7 个组件分别去重后台任务，请求使用共同的 11 秒等待预算，登记与缓存只持短锁。未退出的线程继续占槽，迟到结果不写缓存；可控 DNS 解析入口阻塞及响应头 gate 验证实际 HTTP 入口的请求有界返回、并发不额外启动读取。 |

独立复审又在版本查询中复现两处问题并推动修复：较早等待者超时不能作废较晚创建的共享任务；已经异常结束的 Future 必须释放槽位，避免所有重试永久复用异常。新增回归以同一真实后台任务和 Event 协调验证前者，并使用实际深层 JSON 解析、异常任务及成功重试验证后者。独立重放确认旧等待者也不会删除后继任务；复审范围内无剩余可执行的 P1 / P2 发现。

## 86 条告警处置索引

文件名按下列目录前缀解释；原始行号以基线导出清单为准，重构后的行号不作为固定标识。相同规则和依据的条目合并展示，每个 ID 只出现于一条处置行。

### AI / MCP：14 条修正、16 条保留

源文件相对 `plugins/sqlseed-ai/src/sqlseed_ai/`，测试相对 `plugins/sqlseed-ai/tests/`；MCP 文件另列完整路径。

| ID | 文件 / 规则 | 处置与依据 |
| --- | --- | --- |
| 1, 7 | `mcp.py` 与 `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/server.py`；`CodeDuplication` | 保留。重复的是两个独立发行包使用 Core 的导入声明；共享算法已在 Core，不增加跨插件导入聚合层。 |
| 2, 3 | `_json_utils.py`；`consider-using-assignment-expr` | 修正。合并单次求值与判定，保持空对象与失败 `None` 的区别、有限结构恢复规则。 |
| 4 | `analyzer/_caller.py`；`too-complex` | 修正。分离 completion 解码与请求 / 异常处理，保留模型回退、严格分类及兼容空正文行为。 |
| 5 | `analyzer/_tool_calling.py`；`too-complex` | 修正。分离 tool choice 解码，同时修复上述非对象参数崩溃。 |
| 6, 8 | `cli/ai_commands.py`、`refiner.py`；`consider-using-assignment-expr` | 修正。合并赋值与判断，保留空结果退出、目标校验及缺表的提前拒绝；关联修复见上表。 |
| 9–12 | `test_ai_preserve_names.py`；`wrong-import-position` | 保留。依赖导入必须位于顶层 `pytest.importorskip("sqlseed_ai")` 之后，保证缺可选插件时先跳过。 |
| 13–16 | `test_cli_suggestion_diagnostics.py`；`wrong-import-position` | 保留。同一可选插件边界；普通内部导入仍会暴露损坏安装，不改成子模块级跳过。 |
| 17, 18 | `test_cli_suggestion_identity.py`；`wrong-import-position` | 保留。同上，不为导入排序改变缺插件语义。 |
| 19, 20 | `test_nonweb_ai_boundaries.py`；`CodeDuplication` | 修正。共用函数级旧缓存 fixture，路径逃逸、hash 失配、真实 symlink 与权限跳过断言分别保留。 |
| 21, 22, 29, 30 | `test_refiner_json_recovery.py`、`test_refiner_table_boundaries.py`；`wrong-import-position` | 保留。同一可选插件存在性检查与正常内部导入顺序。 |
| 23–28 | `test_refiner_json_recovery.py`；`CodeDuplication` | 修正。提取真实数据库 fixture、失败后恢复流程和写入结果检查；安全反馈、2 次预算耗尽、零写入及显式生成后 3 行值为 7 的断言仍独立验证。 |

### Web 源码：20 条修正、7 条保留

文件相对 `plugins/sqlseed-web/src/sqlseed_web/`。

| ID | 文件 / 规则 | 处置与依据 |
| --- | --- | --- |
| 31 | `_application.py`；`too-complex` | 修正。独立注册异常处理器，保持中间件与路由顺序、结构化响应和脱敏行为。 |
| 32 | `_windows_process.py`；`too-complex` | 保留。平台 guard 下多个定义被聚合为复杂度 51；不为模块级聚合数字拆散 Windows 专属定义。 |
| 33 | `_windows_process.py`；`consider-using-assignment-expr` | 保留。显式命名重复句柄后追踪其所有权和失败清理，比条件内赋值更清楚。 |
| 34 | `_windows_process.py`；`consider-using-with` | 保留。`Popen` / Job 句柄需要显式转交与释放顺序，不能由普通上下文退出替代。 |
| 35–37 | `messages.py`；`consider-merging-isinstance`、`consider-using-assignment-expr` | 修正。合并类型判断与单次求值；保留消息描述符、英文回退及 `KeyError` 引号恢复。 |
| 38 | `plugin_environment.py`；`no-else-return` | 保留。平台 `else` 使 mypy 正确解析 Windows 专属导入和实现。 |
| 39 | `plugin_environment.py`；`consider-using-assignment-expr` | 修正。合并 spawning 上下文获取与判空，不改变句柄转交条件。 |
| 40, 41 | `plugin_management.py`；`too-complex` | 修正。分离计划审阅、安装准备、下载后复验及终态清理；计划仍在同一锁内验证后原子替换，失败清理见上表。 |
| 42 | `plugin_process.py`；`too-complex` | 修正。提取安装器等待逻辑，进程与输出读取共享 deadline；先终止、再释放资源的顺序不变。 |
| 43 | `plugin_updates.py`；`consider-using-with` | 保留。后台线程拥有 semaphore 直到真实退出；调用方超时后不能由 `with` 提前释放并超量启动。 |
| 44 | `plugin_updates.py`；`too-many-boolean-expressions` | 保留。下载 URL 的 6 项安全条件逐项可读，合并成不透明抽象没有改善校验。 |
| 45–49 | `plugin_updates.py`；`consider-using-assignment-expr`、`bad-builtin`、`too-complex` | 修正。简化单次读流、改显式迭代并分离 wheel 过滤与排序；解释器 tag 优先级、文件名决胜、hash / URL / metadata 校验不变。 |
| 50 | `settings_environment.py`；`consider-using-assignment-expr` | 修正。合并命令参数生成与判空，保留 shell 引用及只展示、不执行的边界。 |
| 51 | `settings_updates.py`；`consider-using-assignment-expr` | 修正。合并读取与 EOF 判断；关联的总预算、共享任务与异常槽位修复见上表。 |
| 52 | `workbench_ai.py`；`too-complex` | 修正。分离模型 HTTP 错误映射，保持可选 AI 延迟导入、错误优先级及上游内容脱敏。 |
| 53, 56 | `workbench_execution.py`、`workbench_store.py`；`line-too-long` | 修正。拆分表达式，消息键、异常类型及原有局部规则说明不变。 |
| 54 | `workbench_runtime.py`；`too-complex` | 保留。迭代强连通分量算法避免深图递归；66,067 个图与独立传递可达性 oracle 穷举对照一致。 |
| 55 | `workbench_runtime.py`；`consider-using-assignment-expr` | 修正。合并栈弹出与访问判断，不改变强连通分量算法。 |
| 57 | `worker_control.py` 所报依赖环；`cyclic-import` | 修正。将纯文本诊断提取到 `_diagnostic_text.py`，使 `messages.py` 与 `diagnostics.py` 不再互相依赖；三模块 6 种新进程导入顺序全部成功，消息与 SQL 参数脱敏保留。 |

### Web / Core 测试：19 条修正、10 条保留

除末行外，文件相对 `plugins/sqlseed-web/tests/`。

| ID | 文件 / 规则 | 处置与依据 |
| --- | --- | --- |
| 58 | `complex_graph_fixture.py`；`confusing-with-statement` | 保留。`closing` 与 connection 双上下文明示事务退出后关闭真实 SQLite；嵌套形式又违反现有 Ruff `SIM117`，无需增加仅供消警的辅助层。 |
| 59 | `complex_graph_fixture.py`；`consider-using-assignment-expr` | 修正。外键检查只执行一次，失败仍报告完整 violations。 |
| 60, 61 | `test_complex_graph_fixture.py`；`redefined-outer-name`、`reimported` | 修正。同一处冗余 `UIState` 导入删除，复用模块导入；不计为两处产品缺陷。 |
| 62–65 | `test_i18n_component_paths.py`；`useless-return`、`use-implicit-booleaness-not-comparison`、`line-too-long` | 修正。删除冗余返回、拆 DDL；本地列表可直接判空，接口返回仍经 `assert_empty(..., list)` 保留类型契约。 |
| 66, 67 | `test_i18n_validation_paths.py`；`line-too-long`、`use-implicit-booleaness-not-comparison` | 修正。拆分自引用 DDL，使用 `assert_empty(..., dict)` 继续拒绝 `None`、`False` 和错误列表形状。 |
| 68 | `test_plugin_management.py`；`use-implicit-booleaness-not-comparison` | 修正。局部调用列表判空；环境 metadata 不变、任务尚未创建和后续恰好一次调用断言保留。 |
| 69, 70 | `test_plugin_process.py`；`CodeDuplication` | 保留。共同 Windows 故障设置分别服务延迟释放与清理失败重试，准确时序和二次重试断言独立。 |
| 71, 72, 76, 78 | `test_plugin_updates.py`；`keyword-arg-before-vararg`、`use-implicit-booleaness-not-comparison`、`consider-using-tuple` | 修正。版本参数显式必填、固定迭代值改 tuple、本地调用列表判空；版本、依赖及无副作用断言保留。 |
| 73, 79 | `test_plugin_updates.py`、`test_settings_updates.py`；`CodeDuplication` | 保留。wheel 下载与 index 查询的短 HTTP 协议替身相似，但 host、headers、redirect、字节上限及预算断言不同。 |
| 74, 75 | `test_plugin_updates.py`；`consider-using-with` | 保留。显式 `acquire(timeout=5)` 表达有界等待；普通 `with` 不能替代，迟到数据不得重建目录的断言保留。 |
| 77, 80 | `test_plugin_updates.py`、`test_supervised_plugins.py`；`CodeDuplication` | 保留。局部生命周期替身分别覆盖恢复快照与 busy / restore 故障、精确阶段顺序，不引入跨场景分支来消重。 |
| 81 | `test_supervised_plugins.py`；`use-implicit-booleaness-not-comparison` | 修正。局部 cleanup 列表判空，保留 `stop → stop → released` 次序和单次安装断言。 |
| 82 | `test_windows_environment.py`；`line-too-long` | 修正。拆分子进程脚本表达式，真实 spawn、硬退出与继承锁语义不变。 |
| 83 | `test_windows_environment.py`；`consider-using-with` | 保留。显式 `Popen` / `finally` 保证有界等待、finish 通知、必要时 kill / reap 与锁回收，不改为隐式无限等待。 |
| 84, 85 | `test_workbench_runtime.py`；`consider-using-tuple` | 修正。固定两项迭代值改 tuple；双向关系、含逗号的列名与精确结果比较保留。 |
| 86 | `tests/test_database/test_sqlite_connection_targets.py`；`use-implicit-booleaness-not-comparison` | 修正。已构造目录列表判空，继续验证 `mode=rw` 不创建目标或诱饵文件。 |

## 已完成的定向验证

下列批次存在重叠，不能相加为独立测试总数；均对应本轮工作树的各次验收，完整检查及提交归属见下一节。

| 范围 | 已观察到的结果与限制 |
| --- | --- |
| AI / MCP 固定 SDK、HTTP / SSE、SQLite 回归 | 344 passed、1 skipped、5 deselected，102.49 秒；随后 fixture 命名调整相关批次 24 passed、1 skipped。symlink 因 Windows `WinError 1314` 权限跳过，真实 LLM 与 PostgreSQL 显式排除。AI mypy 63 个文件、Ruff / format 通过。 |
| Web / Core 测试调整 | 179 passed、1 skipped，113.57 秒；Windows 不支持文件名 `?` 的用例跳过。使用 `ResourceWarning` 和 `PytestUnraisableExceptionWarning` 作为错误；8 个修改测试文件 Ruff / format 通过。 |
| Web 生命周期第一批 | 85 passed、1 skipped、2 deselected，24.08 秒；Windows 跳过 POSIX 进程组语义，真实安装器两项未在此批执行。新增共享任务边界随后复验，不冒充已包含于此批。 |
| 版本查询最终并发回归 | 24 passed，3.17 秒，包含 observer deadline、异常 Future、深层 JSON 和恢复重试；用 Event 与有界 join 控制时序。 |
| 图算法与依赖环 | 66,067 个图与独立 oracle 一致；三个相关模块的 6 种新进程导入顺序成功。 |
| 本地扫描与独立审查 | Pylint 2.17.7 复核 AI 修改范围仅余 14 条已解释的导入顺序提示，Web 生命周期 6 文件报告为空；独立实现复审的两项并发发现修复后重放成功，无剩余 P1 / P2。此结果不是线上 CodeFlow 重扫。 |

## 最终门禁与环境边界

- 最终 Web 消息、图和生命周期联合回归：93 passed（51.74 秒）；Node 前端：958 passed、0 skipped。
- Ruff / format、mypy（174 个源文件）、3 项 import-linter 边界、文档同步和 MkDocs strict 均通过；图穷举及 6 种新进程导入顺序已在修改后复跑通过。
- 首轮完整 pytest 得到 4,100 passed、89 skipped、8 failed。两项失败来自测试替身未接收新增 `strict_json` 参数，接口同步后该测试文件 61 passed，原降级与实际结果断言保留。
- 其余六项首次失败是 LM Studio 返回 HTTP 200 但模型列表为空，真实 completion 返回 `No models loaded`。修正 healer 前提探针后，相关批次 16 passed、6 skipped：只有列表包含所选模型才继续；畸形协议和真实推理错误仍然失败。本轮没有加载模型，不能宣称六项真实推理通过。

- 稳定代码完整 pytest：**4,115 passed、95 skipped**，652.19 秒。17 条 SQLAlchemy 警告在下述兼容性补充中继续处理；没有将跳过的真实服务或平台用例算作通过。
- 本地默认 mutation gate 在独立工作区执行：**246 / 246 killed**，0 survived、0 timeout、0 suspicious、0 skipped。范围为 `unique_adjuster.py` 及默认的两份回归测试；已核对这三个文件与待交付代码一致，不代表全项目变异覆盖。工作区结束后通过管理工具归档，保留日志与结果证据。
- 提交 `c752443` 的 [CI](https://github.com/sunbos/sqlseed/actions/runs/36583328081) 已完成：lint、五包安装验收、性质测试、PostgreSQL integration、Python 3.10 / 3.12 / 3.13、macOS 和 Windows 均成功；[doc-sync](https://github.com/sunbos/sqlseed/actions/runs/36583327585) 成功。PR 的 docs 部署 job 按条件跳过，本地 MkDocs strict 构建另已通过。
- 同一提交的 [Codecov patch](https://app.codecov.io/gh/sunbos/sqlseed/pull/23) 实际覆盖率 **96.64%**，要求 **88.21%**；[CodeFlow](https://app.getcodeflow.com/github/sunbos/sqlseed/pull-requests/23) 的 33 条保留提示逐条复核完成。
- 同一提交的 Sonar quality gate 为 success，但检查摘要报告 **9 条新增问题**。这不等于零问题：本次尚未读取这 9 条的明细。用户于 9 月 30 日要求继续，已从官方来源安装 Sonar CLI 1.9.0；`sonar auth status` 返回 `No saved connection`。用户登录、MCP / hooks 配置、明细核验和问题处置仍待完成，不能据此宣称全部技术债已清空。

### SQLAlchemy 2.0 / 2.1 兼容性补充

完整测试中 15 条弃用警告来自 SQLAlchemy 2.1 将停止为 `mode=memory` 隐式选择连接池；另两类来源提示对应负向测试故意遗漏 `uri=true`。补充修改显式保留 `sqlite` / `sqlite+pysqlite` 命名内存 URL 既有的 `SingletonThreadPool` 策略，不切换连接寿命或改写 URI / 线程参数。负向测试只局部捕获并精确断言预期警告，其他警告仍失败。

- 新增 11 项回归：真实 SQLite 的共享 / 私有命名内存、连接关闭后数据寿命、普通内存、磁盘 URI 持久化、字面百分号和 timeout、自定义 SQLite driver；PostgreSQL 两项仅验证惰性 engine 的默认 pool 配置，不连接服务器，真实 PostgreSQL 验收另由 CI integration 执行。
- SQLAlchemy **2.0.51** 和 **2.1.0** 的同组八文件验收均为 **107 passed、7 skipped**，分别 22.25 / 22.39 秒；将 `SAWarning` 和 `SADeprecationWarning` 视为错误，无非预期警告。七项跳过来自 Windows 平台限制，未改动当前开发环境的依赖版本。
- 补充源码与测试 Pylint 2.17.7 无告警；完整 Ruff / format、mypy（174 文件）、import-linter 与文档同步通过。该小范围补充已独立复核，没有新的 P1 / P2 发现。

### 9 月 30 日补充提交验收

补充代码提交为 `3c5aceb8350dcd2923bdaef569ab0d1dde767439`，与前述 `c752443` 的历史结果分开记录：

- 最终完整 pytest：**4,126 passed、95 skipped**，529.18 秒，0 failed、0 error、无非预期警告。`ResourceWarning`、`PytestUnraisableExceptionWarning`、`SAWarning` 和 `SADeprecationWarning` 均按错误处理。证据为 `sqlseed-hardening-pytest-pool-final.log` / `.xml`；旧的 4,115 项结果属于补充前，不替代本次验收。
- 该提交 [CI](https://github.com/sunbos/sqlseed/actions/runs/36587202195) 的所有实际执行 job 成功，含 PostgreSQL、五包安装、性质测试、Python 3.10 / 3.12 / 3.13、Windows、macOS，以及 lint 中的 Node 测试和 MkDocs strict；[文档同步](https://github.com/sunbos/sqlseed/actions/runs/36587201874) 成功。docs 部署 job 仍按 PR 条件跳过。
- 该提交 CodeFlow 为 **0 errors、33 warnings**，SQLite 补充没有新增告警；Codecov 增量覆盖率为 **96.67%**，门槛 **88.21%**。Sonar 检查仍为 success、**9 条新增问题未核验**，不将成功状态解释为零问题。

后续提交以 [PR #23](https://github.com/sunbos/sqlseed/pull/23) 当前 head SHA 的检查和验收记录为准。PR 保留草稿状态，未合并、打 tag 或发布。

### 零告警目标的继续收口

剩余 33 项已按原始 ID 逐项修改，没有增加 suppression、扩大扫描排除范围或降低阈值：

| 原始 ID | 修改及保留的行为 |
| --- | --- |
| 1、7 | AI MCP 使用 Core 公共接口和路径模块调用，消除重复导入段；不增加跨插件依赖。 |
| 9–18、21–22、29–30 | 可选 AI 包使用标准导入边界，只在缺少顶层 `sqlseed_ai` 时跳过；实际 Core-only 环境五个模块均 skip，内部模块损坏和依赖损坏的实际副本均报 collection error。 |
| 31–33 | Win32 API、句柄拥有者、子进程 guard 的职责分开；Popen 上下文先终止并排空 Job，再等待和关闭句柄。创建失败仍保留锁直到确认排空。 |
| 36 | 继承环境锁先处理 POSIX 返回路径，Windows spawn 仍复制同一文件对象；删除多余 else 不改变锁语义。 |
| 43–44 | 网络准入上下文通过 ExitStack 交给真实工作线程，观察者超时不释放槽位；下载地址分为可信来源和包路径校验，全部六项条件保留。 |
| 54 | 将迭代 DFS 完成顺序与反向图遍历分离；132,134 次穷举对比及 50,000 节点深链、整环、阻塞下游场景保持精确成员与顺序。 |
| 58、69–70、73–75、77、79–80、83 | SQLite 事务/关闭、HTTP 协议、生命周期 Controller 与有界资源管理使用共同 helper；业务断言、故障顺序、五秒等待、真实进程与锁回收验证保留。 |

新增八项边界回归针对 Codecov 报告中实际缺失的十行：拒绝无效 wheel/index、缺失已校验更新计划、真实安装器输出失败的回收、模型连接失败后的安全重试，以及非 spawn 的 Windows 句柄转移拒绝。十行在本地 Windows coverage 中全部执行，不推定它们已经在 Linux 或线上报告覆盖。

本地完整 pytest 为 **4,137 passed、95 skipped**，551.46 秒，四类资源/SQLAlchemy warning 均按 error。最后平台结构调整后的相关回归另为 **154 passed、3 skipped**；Ruff、格式、Windows/Linux mypy（174 文件）、import-linter、文档同步和 MkDocs strict 通过。Core 默认 mutation gate 的目标和测试文件本次未改，仍对应前述 246/246 killed 的证据。独立代码复审发现的平台类型和启动中断所有权问题均已修正。

线上 CodeFlow、Codecov、CI 必须以继续收口提交的准确 head 为准，尚未用本地结果替代。Sonar CLI 登录仍待用户完成；此前 success 摘要中的九项新问题还未读取明细，因此当前不能宣称整个项目的所有外部分析已经归零。

## 证据归属

原始文件保留于任务系统 TEMP，不作为产品运行依赖：

- `sqlseed-codeflow-e8ecd29-warnings.json`：86 条基线告警的 ID、规则、路径、行号及原文。
- `sqlseed-codeflow-resolution-ai.json`、`sqlseed-codeflow-resolution-ai-validation.json`：ID 1–30 的依据、行为回归及静态检查。
- `sqlseed-codeflow-resolution-tests.json`：ID 58–86；其中 68、79、80、81 的最终结论由下一份报告覆盖，不能把中间 `delegated` 算作未处理。
- `sqlseed-codeflow-resolution-web-lifecycle.json`：ID 40、41、51、68、79、80、81，包含两项独立复审修复和最终并发验证。
- `sqlseed-codeflow-root-checks.json`：图穷举与新进程导入证据。`sqlseed-codeflow-root-tests.json` 中 61 项结果及旧缺陷重放属于基线审计，不充当修复后最终全量验收。
- `sqlseed-codeflow-independent-implementation-review.json`：审查范围、源文件 hash、两项发现、修复前后重放及最终结论；平台专项和完整门禁不在其声明范围。
- `sqlseed-hardening-pytest-final.log` / `.xml`、`sqlseed-hardening-node.log`：稳定代码的完整 Python / Node 结果。
- `sqlseed-hardening-mutation-isolated.log`、`sqlseed-hardening-mutation-results.txt`：独立工作区的默认 mutation gate 结果。
- `sqlseed-pool-final-2.0.log`、`sqlseed-pool-final-2.1.log`：兼容性补充的双版本验收；后续全量复验另存 `sqlseed-hardening-pytest-pool-final.log` / `.xml`。

本轮使用隔离测试数据库、临时缓存与受控协议输入；没有以清理告警为由删除用户数据、停止用户预览服务或安装 / 卸载用户环境组件。真实模型和跨平台验证仅以各自实际运行结果为准。
