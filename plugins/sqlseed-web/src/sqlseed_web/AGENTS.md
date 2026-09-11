# sqlseed_web 后端

上层见 [包指南](../../AGENTS.md)；前端另见 [static/AGENTS.md](static/AGENTS.md)。

v8 整体重建已完成；当前细化以 [可用性与 AI 辅助计划](../../../../docs/superpowers/plans/2026-09-07-workbench-usability-ai.md) 为准，保留 [v8 重建契约](../../../../docs/superpowers/plans/2026-09-07-web-v8-rebuild.md) 的样式基线；导航按后续设置评审扩展为四项。以下原有 `/api` 行为是后端兼容边界，不要求保留旧页面或导航；正式 `/api/workbench` 及可选 AI 的规则见后文。

## 模块与 API 边界

- [app.py](app.py)：`create_app()` 挂载旧 `/api`、`/api/workbench` 与 `/api/workbench/ai` router、`/static` 与 `/`；`/api/health` 也在这里。保留静态资源 `Cache-Control: no-cache`，本项目没有 asset hashing。
- [api.py](api.py)：原有 endpoints；[state.py](state.py)：进程内 `UIState` singleton、连接、AI 会话覆盖与 jobs。
- [workbench.py](workbench.py) 是正式工作台 HTTP 契约；[workbench_schema.py](workbench_schema.py) 提供成组外键、完整约束、结构 hash 与签名生成的参数目录；[workbench_runtime.py](workbench_runtime.py) 提供确定性检查、预览和服务端顺序执行；[workbench_store.py](workbench_store.py) 保存版本化草稿及固定运行快照。
- `/api/meta/*` 提供 generators/params、hooks、providers、AI 状态、locales、dialects；不要复制 core 计数。参数来自 `BaseProvider._gen_*` 签名，pluggy firstresult 标记读 `fn.sqlseed_spec`。
- `/api/connections` 管理连接，新连接弹窗复用该接口；连接下的 tables/schema/mapping/yaml-template、topo-order、preview/fill/rows/query 保留旧 API 兼容。正式工作台通过 `/api/workbench` 检查、预览和运行。
- `/api/config/parse` 通过临时文件调用 core `load_config()`，`finally` 删除文件；`serialize` 使用 safe YAML。解析成功不表示 generator 名称有效，未知名称仍可在生成/验证时失败。
- `config_to_dict()` 使用完整 Pydantic `model_dump`；新增配置字段时仍需核对前端往返，避免手工白名单漏字段。
- `/api/fs/browse` 列出服务器目录，默认隐藏非 DB 文件，始终跳过 dotfiles；浏览器 file input 不能提供服务器绝对路径。

## 连接与后台任务

- 连接请求恰好提供 `db_path`/`url` 之一。每个连接持有长生命周期 `DataOrchestrator`；连接失败时清理已注册对象。
- 同目标多连接是有效用法。旧 API 的长生命周期 orchestrator 保留独立 provider/locale；正式工作台的 provider/locale 属于配置，并按完整配置构建执行实例，不能用旧连接默认值覆盖文档。`group_key`、`group_index`、`group_size` 仅做显示分组，不是跨连接锁。
- [sqlite_target.py](sqlite_target.py) 统一 SQLite 的分组、写入准入与配置身份，按 SQLAlchemy 传给 sqlite3 的实际 URI 参数识别文件、具名共享内存和私有内存。普通文件路径的既有配置 hash 保持不变；共享内存按名称、私有内存按 conn_id 隔离，不能把未启用 `uri` 的 `mode=memory` 当作内存库。Web 不支持自定义 SQLite VFS；实际 URI 带 `vfs` 时在连接注册、数据库打开前拒绝，不能忽略 `memdb` 等 VFS 导致同名不同库被合并。
- SQLite URI 中解码后的 NUL、原始 TAB/CR/LF、无效 UTF-8 百分号编码也在注册前拒绝：SQLite 字符串截断与 Python URL 清理/替代解码不同，不能把异常编码折叠成另一目标。合法 UTF-8 与经过百分号编码的 TAB/CR/LF 文件名仍按真实路径识别。
- fills 在后台线程运行，通过 `state.connection_operation(conn_id, job_id=...)` 领取已预留的任务；交互请求不排队等待连接锁，忙碌立即返回 HTTP 409。不得让同一 orchestrator 并发 `fill_table()`。
- `create_job()` 原子预留连接；同一数据库目标只能有一个填充任务，其他数据库可并行。SQLite 规范路径、file URI 和共享内存身份；PostgreSQL 只规范 URL 中已知端点及有效参数，不宣称识别 DNS 别名、service 或代理后的物理身份。worker 初始化、启动或终态持久化失败也必须释放任务占用。
- job 终态通过 `complete_job()` 原子发布 result、错误、行数和完成时间；非空 `GenerationResult.errors` 必须发布 error，不能报告成功。
- 创建任务与关闭连接受同一状态锁协调；排队/执行中的任务阻止关闭（HTTP 409），已失效连接的 worker 必须进入 error 终态。HTTP polling 使用任务快照。
- `GenerationResult.count` 是写入行数；`Job.rows_inserted` 是 Web 层字段。旧 `/api` fill 进度来自行数差值轮询，是近似值，不是核心进度 callback；不能把这种进度方案用于正式工作台的精确提交结果。
- SQL 标识符用 `validate_table_name()` + `quote_identifier()`；`run_query()` 当前只接受单条 SELECT，修改查询接口时保留该边界。
- 旧 `/api/connections/{id}/tables/{table}/schema` 的 `unique_columns`、`skippable` 和 `ColumnInfo` 驱动历史面板；FK 字段为 `column`/`ref_table`/`ref_column`，均是单数。新工作台必须使用独立完整 schema 契约，保留成组列映射和 namespace，不能沿用此简化形状。
- Web locale 使用 Faker 风格（`zh_CN`/`en_US`）；`SUPPORTED_LOCALES` 与 `MimesisProvider.set_locale` 的映射保持一致。

## 可选 AI 边界

- `sqlseed_ai` 必须在函数内 lazy import；metadata/config 缺失 AI 时返回 `available: false`，heal endpoints 用 HTTP 503。
- [workbench_ai.py](workbench_ai.py) 是正式工作台可选 AI 接口：配置与检测复用 env + 会话设置，分析复用 `AIConfig` / `SchemaAnalyzer`，返回待审阅补丁，不运行自动修复或填充。
- `/ai/suggest` 保留 JSON 响应兼容，`Accept: application/x-ndjson` 使用 [workbench_ai_stream.py](workbench_ai_stream.py) 发布实际 context/model/validation/preview 阶段与唯一终态。单次请求固定 AIConfig 快照；同连接 AI 门禁直到 worker 真正退出才释放，取消或 180 秒等待预算不等于硬中断 SDK 网络调用。ASGI 2.3 与 2.4 的断开监听不得竞争同一个 receive。
- AI 候选样例经实例级 DataStream 尝试预算和合作式取消检查，不全局修改重试常量。保留结构化 validation issues（表、列、生成器、约束），禁止暴露已有记录、密钥或原始 SDK 错误；catalog 必须解释 pattern 的正则语义及当前 provider 的 phone/template 差异。
- AI 范围支持整库、指定表多选、指定列多选及当前/勾选表快捷项，独立于生成范围。`allowed_targets` 限定修改列；上下文保留所在整表及必要上游结构、约束、生成器目录、全局引擎/语言和用户业务说明，不包含连接地址、凭据、row_count、运行时父键或已有记录。全部 `table_drafts` 参与保护和候选校验，不能因表未勾选丢失高级规则。schema/业务说明始终视作数据。
- 建议经过范围、表列、generator 目录、参数及 `ColumnConfig` 校验。新关系仅由 [workbench_ai_relations.py](workbench_ai_relations.py) 编译 copy/concat/product/date_offset 模板，验证类型、NULL、来源可用性及新旧 core DAG；保留 PK/FK/实际使用数据库默认值的列/计算列和已有 derived/native 规则，拒绝模型原始表达式、原生方法或文件路径。整份候选配置只读校验，相关补丁带 group_id 并原子审阅/应用；样例检查不宣称证明任意 SQL CHECK。分析前后复核 schema hash，网络期间释放连接操作锁。
- 新旧 AI 配置响应均不能回传 API key，只给是否配置的标记；修改设置时空密钥保留已有会话密钥，旧接口显式空请求仍重置会话覆盖。密钥不得保存进工作台文档或运行记录。
- `/heal/validate`、`/heal/repair`、`/heal/auto` 分别委托 Layer 2、3、5；保持修复算法在 AI 包，不搬入 Web。
- auto-heal 复用 `sqlseed_ai.runtime` 的 `build_ai_config()`、`build_llm_client()`、`build_heal_orchestrator()`；不导入 CLI 私有工厂。共享服务使用普通 Python 异常，CLI/Web 入口各自转换错误，修改签名时一并检查调用者与资源释放。
- 有效 AI 配置从 env 合并会话 override，再由单次 auto-heal 请求覆盖；空 override 值回退到 env。metadata 与 `/api/ai/config` 的状态应一致。
- `/api/ai/test-connection` 探测 `resolve_base_url().rstrip('/') + '/models'`；本地 Ollama/LM Studio 只要求服务可达，不要求用户填写 API key。
- `AI_BACKENDS` 给出基础展示顺序，heal 页面会把有效 backend 提到首位；两个地方共同决定用户看到的顺序。
- auto-heal 产出 YAML，不执行数据填充；`_CountingLLMClient` 记录真实 LLM 调用次数，确定性流程可能为 0，不能把“完成”描述成必然调用过 LLM。
- AI 连接目标保持与 core 一致：含 `://` 的目标按 URL 传递，包括 `sqlite+pysqlite://`；不能用固定 dialect 前缀当文件路径判据。

## 正式工作台不变量

- 文档经完整 `GeneratorConfig` 校验，未知 root/table 字段必须报错；目标仅由明确的连接注入，保存内容不带 `db_path`/`url` 或凭据。不能因为面板没有编辑器就丢弃高级配置。
- 保存校验 schema hash 和乐观 revision；开始运行时在 store 同一事务校验当前 revision 与快照，再保留不可变文档。检查和运行都重新读取真实结构及来源，不能相信前端的成功标记。
- 列表、打开和运行只接受当前 canonical `target_key`，不提供或接受旧身份 aliases。旧 URI hash 可能恰好属于另一个真实的 `file:` 前缀文件，不能仅凭当前连接写法推导旧 hash 并自动授权；没有可信身份版本的记录不得通过同 schema 或解析 target_label 猜库迁移。普通路径的旧 key 不变；身份发生变化的旧 URI 配置与运行仍保留可导出，由用户明确导入当前目标创建新配置，历史运行快照不改。历史记录未存原始连接或身份算法版本，旧错 hash 与真实字面 `file:` 路径 hash 的反向碰撞无法可靠区分，这是既有数据的限制，不自动推断或重绑。
- 结构图方向父→子；复合 FK 是同一条边的成组列映射。跨 namespace 或不存在的来源保留只读节点，不能把它们映射到同名默认 schema 表。
- SQLite rowid 分配优先使用 core 的 `ColumnInfo.is_rowid_alias` 事实，仅旧 metadata 缺失时使用兼容查询。部分索引不得进入无条件 `unique_constraints`；其条件保留在 `conditional_indexes` 并参与 schema hash，谓词变化会使旧检查失效。
- 空父表在所选生成计划内是合法依赖。预览不能虚构尚未生成的父键，但仍须验证独立字段的生成器参数和表达式。
- 未选父表存在有效引用键时可以只读引用；未选且缺少必需来源时才阻止对应生成。依赖检查返回来源是否可用、数量与范围事实，不向浏览器暴露实际父键列表。追加写入的自增 ID 由数据库分配，不能为改善预览展示而重置序列。
- 工作台的保存、检查和执行不依赖 AI；AI 仅在用户请求时分析并产出待审阅建议，用户选中应用后进入同一份配置，仍由确定性检查验证。执行保持 `fill_table(skip_ai=True)`，不能在写入过程中隐式更改已经确认的规则。SQLite 清空使用明确执行策略和单事务，不能通过 core 配置 clear_before 隐式开启；PostgreSQL 清空、任意服务器 Python transform、跨表通用循环等未接入能力必须明确阻止，不可忽略。
- Worker 持有连接操作锁并逐表执行，失败后其余表 `not_run`。已提交数量来自 `GenerationResult.count`，不能用总行数差冒充精确值。记录异常文本先脱敏，避免 SQLAlchemy 参数和连接密码落盘。
- Store 使用 WAL、短事务、独立连接；`get_store()` 按路径缓存，只有首次初始化恢复遗留任务为 `interrupted`，不得在每次轮询时打断活跃任务。中断记录 `row_counts_exact=False`。

## 验证

从仓库根显式运行 `pytest plugins/sqlseed-web/tests/ -q`。并发、schema 约束和配置往返应使用真实 SQLite；AI 可达性测试可替换 HTTP 请求。

## 显式执行策略

- `workbench_execution.py` 负责只读清空规划。POST execution-plan 使用保存的 draft/revision/schema/config 绑定，返回实际表/行数、删除顺序、能力和 plan_hash。POST runs 固定 execution/plan_hash；append 为兼容默认，replace_selected 必须重新验证确认计划。
- SQLite replace 使用 SQLAlchemyAdapter.transaction()，父键读取、清空、自引用更新和批次写入共用连接；不关闭 FK、不自动 CASCADE、不在事务提交前报告已提交。失败回滚原行与序列，运行结果明确 rolled_back。PostgreSQL replace、范围外引用、触发器和未覆盖自引用等通过服务端能力检查阻止。
- 配置删除只删除可变草稿，不删除已提交运行快照、任务和业务记录；重命名/复制/删除均按 revision 检查。

- 2026-09-09 实测修正：AI DEFAULT 保护按当前实际生成模式判断；生成器主动提供值时可优化，真正省略使用 DEFAULT 时保持保护。PK/FK、计算列及已有派生/原生规则继续保护。追加失败只有完整精确计数才能创建剩余配置，扣除已提交行数，保留原快照与已完成表草稿，不自动提交；中断/未知计数/清空模式不能直接推导剩余量。

- 自定义映射/enrichment 涉及 DEFAULT 时，AI 助手先调用只读 eligibility 预检，并与 suggest 共用实际规则解析；响应只含生成模式，不含样例或父键。普通配置不增加请求；编辑、关闭或离页后的旧结果不得打开可分析界面。

## 2026-09-09 应用设置评审

- 用户已批准第四项主导航“设置”，由新 `pages/settings.js` 提供 AI 服务、插件与版本；不恢复旧 meta/heal 页面。普通设置由 Web 的 `ai_settings.py` 持久化，密钥保持环境变量或进程内存且按服务绑定。新环境接口由 `settings_environment.py` 只读汇总当前 Python 环境。
- 工作台 AI 助手仅展示服务/模型摘要与设置入口；范围、业务说明、分析和审阅继续留在助手。`ai-handoff.js` 只在内存保存明确往返的上下文，身份/epoch/schema/生命周期失效时拒绝恢复。设置检测草稿不保存，不以模型列表成功声称推理成功；保存/检测防重复，迟到响应不覆盖新页面。
- AI 普通设置字段为 backend/model/base_url；`SQLSEED_WEB_SETTINGS_PATH` 可覆盖。UI key 不入磁盘，不随跨 endpoint 切换继承，清除只在当前进程有效。配置表单不把同一进程中的设置称为浏览器私有。
- `preview.js` 重新预览保留上次 DOM、选中表和滚动；状态标明旧结果，失败保留旧结果。`preview.css` 只提供首载占位和状态高度。使用当前行为回归与实际浏览器尺寸核验，不能把历史测试数当成本轮验收。

## 2026-09-10 环境状态契约

- 环境条目保留 `packages`/`providers`，补充 `category`、`requirement`、`dependency_ids`、`description`、`install_command` 和 `guidance`。这些是当前产品展示范围内的关系，不是全量 Python 依赖图；版本与 Python 信息继续动态读取。Base 属于内置，Faker 是 Core 必需依赖，Mimesis 可选。
- AI 配置读取、保存和检测返回 `availability_status`（`available`/`not_installed`/`import_error`），保留原 `available`。Web 可选能力要求发行包存在且模块可导入；卸载后缓存模块或 spawn 继承的 editable 源码路径不能让缺包显示可用。已安装加载失败引导修复，不误报未安装，异常文本不回显。
- AI 可用性还需无调用检查当前 Web 所需的 AIConfig 字段、call_llm(stage=...) 与共享 runtime 工厂；旧包可导入不等于接口兼容。Web ai extra 和受管安装目标要求 `sqlseed-ai>=0.2.4.dev0`，不可回退安装缺少工作台接口的 0.2.3。维护进程只读取 metadata，不导入正在变更的包。
- 缺失/异常 AI 仍返回脱敏 `effective` 普通设置，但禁止检测、保存、eligibility 和 suggest；错误带 `component_id=ai`、`recovery_action=install/repair`。`/api/meta/providers` 保留 available 数组并增加 statuses 事实对象。选中缺失 Mimesis 的配置允许保存，check/preview/执行复核返回 `provider_not_installed` 或 `provider_import_error`，不能静默换引擎。

## 只读当前数据

- `workbench_data.py` 提供有界 GET 分页（limit 1–100、offset 非负）和运行目标的已注册连接匹配。读取先领取 connection_operation；run_id 存在时检查 target_key 与运行表范围，不能借活动连接读取另一目标。匹配连接列表不连接或反射数据库。
- 当前数据使用实际目录白名单、标识符引用、参数化分页和完整主键排序；空表保留列信息。BLOB、Decimal、超出 JavaScript 安全范围的整数及非有限浮点数保留可读值，driver 异常脱敏。接口不记录本次新增主键，也不提供写操作。

## 可选组件自动管理

- `supervisor.py` 在默认启动时持有监听 socket 与管理状态，`managed_worker.py` 分别启动业务/维护 worker，`worker_control.py` 以有界匿名 IPC 传递控制与临时会话。保留原 NDJSON，不代理 HTTP。旧 `--manage-plugins` 仅兼容入口；普通网页无需命令切换或手动重启。
- 维护 worker 业务 `/api/` 一律拒绝，仅保留 health、environment 与 `/api/settings/plugins/*`；HTML 固定标识用于首次导航，API 门禁不能依赖前端，受管维护标识不得永久锁定恢复后的导航。
- `plugin_environment.py` 只接受当前解释器与可写独立 virtualenv，解析真实 distribution metadata/Requires-Dist；不使用 import 缓存判断新安装状态。系统/只读/共享系统包/环境外 metadata 不可管理，但保留普通 Web。
- `plugin_management.py` 白名单仅 ai/cli/mcp/mimesis。管理请求检查 loopback client/Host；POST 必须同 Origin 及 token。计划绑定五分钟内 metadata 快照，一次领取。Core/Web/Faker/Base 不接受操作，不自动卸载依赖。`supervised_plugins.py` 仅在新业务就绪后发布任务终态，恢复失败保留页面与只恢复服务的重试入口。
- 默认 supervisor 持有独占环境锁；子进程保留同一 flock 描述符，父 IPC 断开后关闭准入、自然排空工作再退出。外部正常 app 持共享锁，旧维护 app 持独占锁。锁不是外部 pip/Python 进程的强制协调器，不能声称阻止旧版本或任意外部进程。
- `runtime_lifecycle.py` 对所有非管理 HTTP 和真实后台线程计数；原子空闲检查失败返回 409，不强杀生成/AI 线程。`runtime_session.py` 只经内存和 IPC 保存原连接身份、凭据、provider/locale 与完整 AI 覆盖；成功后清除原始快照。内存 SQLite 阻止操作，部分恢复失败单独报告且不创建缺失数据库。
- `plugin_process.py` 使用受控 argv、固定环境、冻结版本 constraints、wheel-only、超时与有界脱敏输出；不得引入任意命令、路径、package spec 或 pip 私有 API。测试真实 pip/uv 只能操作临时 virtualenv 与离线测试 wheel，不得修改当前用户环境。
- 首版维护包变更仅支持 macOS/Linux；Windows 保留普通 Web 与 PowerShell 手动命令，不能在未实现子进程树超时回收前开放界面操作。
