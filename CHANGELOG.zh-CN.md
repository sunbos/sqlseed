# 变更日志

[English](CHANGELOG.md) | **[中文](CHANGELOG.zh-CN.md)**

本项目所有重要变更将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)，
本项目遵循[语义化版本](https://semver.org/spec/v2.0.0.html)。

## [Unreleased]

## [0.2.5] - 2026-10-02

### 新增

- 增加可复用的 `FillOptions` 单表生成参数。既有 `fill()` 关键字调用和默认值保持兼容，显式关键字优先于共享设置。
- Web 工作台、配置管理、运行记录与设置支持简体中文和 English 切换，保留编辑状态，界面语言与生成数据的 locale 分离；随包分发的消息资源同时翻译受支持的后端诊断。
- 增加浅色、深色及跟随系统外观、保存在浏览器中的新建配置偏好，以及包含分发字体的 Web 共用组件样板。
- 支持 Windows 受管组件变更；可选组件更新需审阅依赖、固定其他包版本、核验 wheel 哈希，并恢复服务。
- AI 建议支持应用前微调，预览可在保留上下文的情况下编辑字段规则；未应用修改与当前生成规则分开保存。
- Web 支持 SQLite 已有来源的跨表循环预览与原子追加：环内每条关系必须是已有非空父键的单列外键。生成前固定引用来源，写入前重新核对来源与规则，任一批次失败时回滚整个所选范围的本次新增记录。

### 变更

- 将复杂 AI 解析与关系图布局阶段拆分为职责明确的辅助函数，合并重复 CSS 声明并保持渲染与交互行为。`fill()` 签名内省改为分组参数和带类型的兼容关键字，API 指南保留完整参数参考。
- 简化工作台引导、配置操作与关系图；增加鼠标位置缩放、稳定的悬停几何和可定位到具体表的循环问题。
- 关系图支持手动输入缩放比例，明确节点与关系图例；标签页、流程阶段和复选框提供短暂选择反馈并遵循减少动态效果设置。依赖箭头保持静态，避免暗示正在传输数据。
- SQLite 清空重建受阻时，引导审阅并补齐下游关联表，保留已选写入方式和最后确认步骤。
- Core、CLI、AI、Core MCP 与 Web 统一以 0.2.5 版本交付。插件要求 Core `>=0.2.5.dev0,<0.3`，使用共享连接解析与凭据脱敏；0.2.4 发行包保留原有依赖元数据。
- 同步双语包说明与架构文档，更新品牌标识；用简明历史决策记录替换过期验收日志。

### 修复

- 关闭教程 SQLite 连接，显式清理 Notebook 临时数据库并恢复缓存设置；四份受影响示例增加完整离线执行验收。
- 显式保留 SQLAlchemy 2.0/2.1 下 SQLite `mode=memory` 的连接池行为，消除已弃用的隐式选择，不改变 URI 解析或线程策略。
- AI 工具参数为非对象 JSON 时进入正常格式错误处理；流式优化同样严格检查输出截断，结构损坏的建议缓存按失效处理。
- Web 检查更新的等待预算覆盖 DNS 与响应头阶段；超时后保留在途请求数量限制，迟到响应不会覆盖当前缓存结果。
- 组件操作临时文件清理失败时仍发布明确失败终态，保留安装器退出信息并恢复服务，不自动重试安装。
- AI 单表配置优化在读取建议缓存或调用模型前拒绝不存在或没有列的目标，保留合法空表及 SQLite 标识符解析行为。
- AI 优化建议与缓存配置必须属于请求的同一张表；目标错误的模型响应进入重试，错目标缓存重新生成，不静默改名。
- 数据库采样、列值与行数查询保留已引用的冒号标识符，不再将其误判为 SQL 参数，并保持 JSON 与日期采样值的既有表示。
- 重新审阅组件操作计划时更新安装器快照，避免 pip/uv 临时探测变化持续阻塞安装；执行前仍核验环境与依赖是否改变。
- 保留编码及特殊字符 SQLite 文件 URL 的真实目标身份；打开已有文件或恢复会话时，不会创建已丢失数据库的替代空库。
- 切换数据库时恢复各自未保存的工作台状态；区分配置与数据库不匹配和连接失败，提供返回当前数据库或选择对应目标的入口，切换后的迟到响应不会覆盖新状态。
- 应用规则前定位非法生成器边界；重新读取空库结构后能进入新表；连接失败或运行记录轮询后恢复键盘焦点。
- 连接响应、参数校验错误、异常与诊断日志不再回显数据库凭据；实际运行连接目标保持原样。
- 无效日期范围按配置错误报告，不再耗尽随机取值重试；AI 提示明确既有日期时间合同，错误 JSON 容器交给正常配置校验。
- 区分 AI 的非法 JSON 与空配置，在既有有界重试中反馈安全的格式诊断；未知生成器进入已有配置校验恢复路径。
- 本地 AI 严格输出使用 LM Studio JSON-schema 模式或 Ollama JSON-object 模式。仅在服务器明确拒绝指定格式时尝试一次文本兼容请求；仍执行严格解析与截断检查，认证失败及无关服务器错误不会因此降级。
- 配置了环境代理时，`localhost` 与回环 IP 上的本地 AI 服务仍直接连接；远程服务代理与 HTTPS 证书设置保持不变。
- 按实际原因说明不支持的生成范围、缺失的新样例与自增重置禁用状态；保留其他已成功返回的样例，并将数据库已有记录作为独立只读入口。
- 异步操作失败后保留前端错误反馈与交互状态；改善浅色主题控件对比度、复选框选中状态、检查区间距及诊断和示例字体。
- 升级 PyPI 上传工具以支持 Core Metadata 2.5，并允许通过维护后的工作流发布现有版本 tag，保持其源码提交不变。
- 五个已创建的包统一使用 `pypi` 发布环境，保留各包独立上传任务及发布后验收，并通过保持不变的公开发行文件核验发布权限。
- 覆盖率只上传实际测量的 Python 报告，并在独立密钥环中核验 Codecov 签名者；文档通过受支持的 GitHub Pages API 部署，核对产物来源并限制轮询与取消的等待时间。

### 兼容性

- SQLite 循环追加引用已有父表记录，新生成的循环表记录不会互相引用；每个来源最多使用 100,000 个非空不同键，不绕过 UNIQUE/CHECK 约束，也不增加跨表回填。来源为空、涉及组合或重叠外键或配置关联、PostgreSQL 循环，以及清空循环表后重建，仍不属于当前 Web 工作台支持范围。
- 全选数据表或重置 ID 不能解除不支持的循环。普通无跨表循环的追加保持按表提交；原子回滚适用于已支持的 SQLite 循环追加与清空重建流程。完整边界见 [Web 工作台指南](docs/web-workbench.md)。

## [0.2.4] - 2026-09-13

### 新增

- 通过 `sqlseed-web` 交付 Web 工作台，支持 schema 关系图、字段规则、预览、多表生成、配置保存与运行记录；AI 仍为可选能力。
- 增加 CHECK 驱动的生成器适配、外键覆盖策略与自引用协调生成；PostgreSQL 使用 SQLAlchemy adapter 和 psycopg 驱动。
- 增加基于 contract 的 AI 校验与修复，包含有界模型调用、确定性降级和独立 AI MCP 工具。
- 增加上传后自动执行的正式 PyPI 验收，覆盖全量 wheel、仅 Core/Web 和全量 sdist 的新环境安装，核验文件来源哈希并通过真实入口生成 SQLite 数据。

### 变更

- 离线 Core、CLI、AI、Core MCP 与 Web 以统一 0.2.4 版本五包交付。`sqlseed` 命令需要安装 `sqlseed-cli`；Core 提供 Python API。从 0.2.3 升级前请阅读[迁移指南](docs/migration.zh-CN.md)。
- 兄弟包依赖保持在兼容的 `>=0.2.4.dev0,<0.3` 系列；使用匹配的正式版本或同一组开发构建产物。
- Core MCP 提供两个离线工具；四个 AI 工具通过独立的 `mcp-server-sqlseed-ai` 进程提供，安装 AI 包不会向 Core MCP 进程注入工具。
- 更新中英文 README、用户与 API 指南、包元数据和文档链接；五包分发物均包含完整的 AGPL-3.0-or-later 许可证正文。
- main 全部 CI 任务成功后部署 GitHub Pages；Python 包通过独立、基于版本 tag 的发布流程上传。

### 修复

- 保留类型绑定写入中的 JSON 文档语义，支持合法 ISO 日期时间输入，避免 JSON 双重编码和旧 SQLite 日期配置失效。
- 自引用父节点更新使用完整主键，并检查完整普通 UNIQUE 键；partial/expression index 仍由数据库执行约束。
- 保留用户显式生成约束，追加数据时处理既有 UNIQUE 值，适配 CHECK 范围且不静默替换冲突规则。
- 关闭 SQLite 资源并在失败时清理 Web worker，处理 Windows 路径与 macOS 进程清理问题。
- AI MCP 的进度输出不再进入 stdio JSON-RPC 协议流，并严格执行 AI 修复时间预算。

### 兼容性

- 升级前迁移旧 `sqlseed.cli` 导入和 MCP 客户端工具选择；Core 0.2.3 不能与新插件混用。
- 普通批量填充在后续批次失败时可能保留此前已提交的数据，应检查返回的 count 和 errors。PostgreSQL 复合与跨 schema 外键生成仍有限制，详见迁移指南。

## [v0.1.20]

### 变更

- 将 `test_mapper.py` 和 `test_mapper_camelcase.py` 中重复的 `_col()` 测试辅助函数提取到 `conftest.make_column_info()`，消除 23 行代码重复（CodeFlow R0801、CodeDuplication；SonarCloud Code Smell）

### 修复

- 合并 `test_mapper_camelcase.py` 中重复的测试函数 `test_non_sensitive_order_no_still_integer` 和 `test_snake_case_still_works`，使用 `pytest.mark.parametrize` 参数化（SonarCloud Major）

## [v0.1.19]

### 新增

- 列映射器 `_to_snake_case()` 规范化：camelCase/PascalCase/Hungarian 列名（`sOrderNo`、`sItemNo`、`userName`、`isActive`）在直接匹配失败后自动通过 snake_case 回退解析
- 敏感标识符模式规则：`user_no`、`card_no`、`card_number`、`identity_no`（及 Hungarian 变体 `sUserNo`、`sCardNo`）映射为脱敏字符串，防止真实值通过 FK 解析或 SharedPool 泄露
- `tests/test_mapper_camelcase.py` — 23 个测试用例，覆盖 camelCase 映射、敏感字段脱敏和 `_to_snake_case()` 辅助函数

### 变更

- `pyproject.toml`：`sqlite-utils` 从必需依赖移至可选依赖（与 `HAS_SQLITE_UTILS` 回退逻辑一致）
- `pyproject.toml`：可选依赖组 `notebook` 重命名为 `tqdm`
- `pyproject.toml`：恢复 `plugins/` 到 sdist 排除列表；插件 `pyproject.toml` 新增 sdist 排除配置

### 修复

- `test_fill_with_snapshot` 通过 `monkeypatch.setenv` 将 `SQLSEED_CACHE_DIR` 设置为 `tmp_path`，修复默认缓存目录无写入权限时的 `PermissionError`

## [v0.1.17]

### 新增

- `RichProgressBackend` 新增 `ascii_only` 参数：启用时使用 `"line"` 旋转符（`|/-\`）并省略 `BarColumn`，避免 GBK/Big5/CP936 编码终端的 `UnicodeEncodeError`
- `_can_render_unicode()` 缓存辅助函数，检测 stdout 是否能编码 Rich 的盲文/方块字符（U+280B, U+2588, U+2591）
- `create_progress()` 在 `_can_render_unicode()` 返回 `False` 时自动回退到 `ascii_only=True`，并输出 debug 日志
- `DataOrchestrator` 新增 SQL 操作方法：`execute(sql, params)`、`query(sql, params)`、`fetch_one(sql, params)`、`fetch_all(sql, params)` 用于直接数据库交互
- `BaseSQLiteAdapter._execute(sql, params)` 参数化 SQL 执行方法
- `DatabaseAdapter` 协议新增 `_execute` 方法签名

### 变更

- `RichProgressBackend` 刷新频率设为 1 Hz（原默认 10 Hz），减少终端闪烁
- 测试套件：`TestRichProgressBackend` 和 `TestRichProgressBackendAsciiOnly` 通过 `pytest.mark.parametrize` 合并，消除代码重复

### 修复

- Windows 兼容性：GBK/GB2312/Big5/CP936 编码终端不再因 Rich 进度条的 Unicode 字符而崩溃
- `.gitignore`：移除 `*汇总.md` 规则（不再需要）

## [v0.1.16]

### 新增

- `_utils/paths.py` — `get_cache_dir(subdir)` 平台标准缓存目录工具（macOS `~/Library/Caches/sqlseed/`，Linux `~/.cache/sqlseed/`，Windows `%LOCALAPPDATA%/sqlseed/`），支持 `SQLSEED_CACHE_DIR` 环境变量覆盖
- `_utils/progress.py` 重构为 Strategy Pattern 多后端架构：`RichProgressBackend`（终端）、`TqdmNotebookBackend`（Jupyter）、`NullProgressBackend`（禁用），含自动环境检测
- `generators/_protocol.py` 新增 `GenerationError`（可重试运行时错误）和 `ConfigurationError`（不可重试配置错误）异常类
- `ColumnConfig` 新增 `normalize_dict_input` model_validator：支持 `type` 作为 `generator` 别名、未知键自动归入 `params`、嵌套 `params` 展平
- `DataStream` 新增 UNIQUE 约束耗尽警告日志，包含列名和生成器详情
- `DataStream` RuntimeError 消息现在包含非 skip 列名，便于快速定位问题
- Jupyter Notebook 教程系列（`examples/notebooks/`）：快速上手、列映射、生成器、数据库关联、表达式/DAG、AI 配置、MCP 服务器、测试模式、工具类、CLI 参考

### 变更

- `SnapshotManager` 默认目录从 `./snapshots` 改为平台缓存目录（`get_cache_dir("snapshots")`）
- `AiConfigRefiner` 默认缓存目录从 `.sqlseed_cache/ai_configs/` 改为平台缓存目录（`get_cache_dir("ai_configs")`）
- `cli/main.py` `inspect --show-mapping` 现在使用 `orch._resolve_specs()` 显示准确的列映射（此前使用 `orch.map_column(col)` 会跳过 FK 解析）
- `cli/main.py` `fill` 命令现在会将 `result.errors` 的警告输出到 stderr
- `orchestrator._resolve_user_configs` 支持 dict 风格的 `derive_from`/`expression` 列配置
- 示例数据库（`examples/build_demo_db.py`）重写为幂等 schema 初始化（`ensure_db()`），不再内置种子数据
- **⚠️ Breaking**: `register_shared_pool` 现在只注册 PK 和 FK 列到 SharedPool（此前会注册所有非 PK-skip 列）。同名非 PK/FK 列的隐式跨表关联需通过 `ColumnAssociation` 显式声明
- UNIQUE 列不再被 SharedPool 隐式关联或 template pool 覆盖，避免生成重复值导致 `IntegrityError`

### 修复

- `orchestrator.fill_table` 现在捕获 `sqlite3.IntegrityError`，避免 UNIQUE/FK 冲突导致未处理崩溃
- `UniqueAdjuster` 使用 `params.get("max_length", max_length)` 防止 `max_length` 缺失时的 `KeyError`
- `DataStream._attempt_node_generation` 优雅捕获生成器异常，不再向上传播
- 回溯/无值日志级别从 `warning` 降为 `debug`，减少日志噪音

## [v0.1.15]

### 修复
- CI: 移除 `ExpressionEngine.evaluate` 中不必要的 try/except，解决 SonarCloud S2737 和 CodeFlow try-except-raise 警告
- CI: 为 `PluginMediator.apply_template_pool` 中的 `list()` 调用添加注释说明其必要性（SonarCloud S7504）

## [v0.1.14]

### 修复
- CI: 修复 `test_doc_sync.py` 中的 ruff SIM114/SIM102 lint 错误
- CI: 移除 `test_doc_sync.py` 中所有正则表达式，解决 SonarCloud S5852 安全热点
- CI: 降低 `_extract_number_before_keyword` 辅助函数的认知复杂度

### 新增
- CLAUDE.md 中添加文档同步规则映射表
- 文档同步验证测试 (`tests/test_doc_sync.py`)

## [v0.1.13]

### 新增

#### 核心引擎
- 跨表关联支持：`ColumnAssociation` 配置模型，支持显式声明源表/源列映射
- 隐式关联：`SharedPool` 通过同名列自动匹配跨表 FK 引用
- `EnrichmentEngine` 数据分布推断，从现有表数据推断枚举列和值范围
- `UniqueAdjuster` 唯一列参数自动调整，确保生成数据满足 UNIQUE 约束
- `database/_compat.py` 新增 `HAS_SQLITE_UTILS` 标志，运行时检测 sqlite-utils 可用性

#### 数据生成器
- 新增 7 个生成器类型：`username`、`city`、`country`、`state`、`zip_code`、`job_title`、`country_code`
- `ColumnMapper` 精确匹配规则从 68 扩展到 74 条

#### AI 插件（sqlseed-ai）
- 自动模型选择：`_model_selector` 按 Gemma 4 优先级自动选择（26B MoE → 31B Dense → 4B → 2B），支持多后端（Google AI Studio、LM Studio、Ollama）
- 结构化输出：`response_format: json_object` 强制 LLM 返回 JSON
- Few-shot 示例库：4 个典型场景（用户表、银行卡表、订单表、员工表）
- `AiConfigRefiner` 自纠正闭环：自动检测并修复无效配置，最多 3 轮重试
- 文件缓存：`.sqlseed_cache/ai_configs/` 带 schema hash 校验，`--no-cache` 跳过
- 预计算模板池：`sqlseed_pre_generate_templates` Hook，AI 为复杂列预生成候选值
- 错误摘要系统：`errors.py` 智能分类错误类型
- 环境变量：`SQLSEED_AI_API_KEY`、`SQLSEED_AI_BASE_URL`、`SQLSEED_AI_MODEL`、`SQLSEED_AI_TIMEOUT`

#### MCP 服务器（mcp-server-sqlseed）
- `sqlseed_execute_fill` 新增 `enrich` 参数，支持数据分布推断
- `sqlseed_inspect_schema` 返回 `schema_hash` 字段

#### CLI
- `fill` 命令新增 `--enrich` 标志
- `fill` 命令新增 `--no-ai` 标志，跳过 AI 建议和模板生成
- `ai-suggest` 命令新增 `--verify/--no-verify`、`--timeout` 参数
- `fill` 命令使用 `--config` 时 `db_path` 改为可选

#### 测试与示例
- 新增 `test_cli_yaml_priority.py`，覆盖 CLI YAML 优先级场景
- 新增 `examples/ai_generation_demo.py` 使用示例

### 变更

- `ExpressionEngine` 正则表达式模式简化
- 代码结构和类型注解优化，移除不必要的延迟导入
- CI 工作流扩展：ruff 检查覆盖 `plugins/` 目录，添加并发控制
- 更新依赖版本限制
- 全面重写项目文档：CLAUDE.md、README.md、GEMINI.md、AGENTS.md、architecture.md
- 重写 `plugins/sqlseed-ai/README.md` 和 `plugins/mcp-server-sqlseed/README.md`

### 修复

- ruff lint 清理，允许中文全角字符（`：`、`（`、`）`）
- 移除 `sqlite3.OperationalError` 不必要的捕获
- `ProviderRegistry.register_from_entry_points()` 修正非 provider 入口点的区分逻辑

### 移除

- 移除 `docs/superpowers/` 目录（过时的设计文档）
- 移除 `suggest.py` 和 `nl_config.py`，功能由 `SchemaAnalyzer` + `AiConfigRefiner` 替代

## [v0.1.12]

### 新增

#### 核心引擎
- 核心编排引擎 `DataOrchestrator`，支持流式批量生成
- `ColumnMapper` 9 级策略链（精确匹配 → 模式匹配 → 类型回退 → 默认）
- `DatabaseAdapter` Protocol，含 `SQLiteUtilsAdapter` 和 `RawSQLiteAdapter`
- `PragmaOptimizer` 三级优化（LIGHT / MODERATE / AGGRESSIVE）
- `DataProvider` Protocol，含 `BaseProvider`、`FakerProvider`、`MimesisProvider`
- `DataStream` 流式数据生成器，内存高效的批量处理
- `RelationResolver` 外键依赖拓扑排序
- 基于 `pluggy` 的插件系统，11 个 Hook 点
- CLI 命令：`fill`、`preview`、`inspect`、`init`、`replay`、`ai-suggest`
- Python API：`sqlseed.fill()`、`sqlseed.connect()`、`sqlseed.fill_from_config()`、`sqlseed.preview()`
- YAML/JSON 配置文件支持
- 配置快照保存与回放
- SQL 注入防护（`quote_identifier()` 工具）

#### v2.0 — 列 DAG 与表达式引擎
- `ColumnDAG` 列依赖解析，基于拓扑排序
- `ExpressionEngine` 基于 `simpleeval` 的安全表达式求值，带基于线程的超时保护
- `ConstraintSolver` 唯一性约束求解，支持重试和回溯
- `TransformLoader` 用户 Python 脚本动态加载（`importlib`）
- `SharedPool` 跨表值共享，维持引用完整性
- `IndexInfo` 数据类和 `get_index_info()` 加入 `DatabaseAdapter` Protocol
- `get_sample_rows()` 方法加入 `DatabaseAdapter` Protocol，用于上下文嗅探
- `sqlseed_ai_analyze_table` Hook（firstresult），AI 驱动的 Schema 分析
- `sqlseed_shared_pool_loaded` Hook，跨表关联追踪

#### AI 插件（sqlseed-ai）
- `SchemaAnalyzer` LLM 集成（OpenAI 兼容 API）
- 上下文嗅探：提取列、索引、样本数据、外键供 LLM 分析
- `AIConfig` 可配置模型、API Key 和 Base URL
- CLI `ai-suggest` 命令，AI 驱动的 YAML 生成

#### MCP 服务器（mcp-server-sqlseed）
- `sqlseed_inspect_schema` 工具 — 检查数据库 Schema
- `sqlseed_generate_yaml` 工具 — AI 驱动的 YAML 配置生成
- `sqlseed_execute_fill` 工具 — 执行数据生成
- 基于 FastMCP 的服务器

### 修复
- Hook `firstresult` 语义与设计文档对齐
- `validate_table_name` 增加正则验证
- 表达式引擎增加超时保护（默认 5 秒）
- `fill_from_config` 中 transform 属性正确传递
