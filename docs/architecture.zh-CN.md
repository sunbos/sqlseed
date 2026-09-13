# sqlseed 架构图

[English](architecture.md) | **[中文](architecture.zh-CN.md)**

> 本文档使用 Mermaid 图表可视化 sqlseed 的整体架构和各模块内部结构。

***

## 1. 整体系统架构

本文描述 `main` 的五包实现；安装与已发布版本的区别见[升级说明](migration.zh-CN.md)。
Core 不依赖入口插件，`DataStream` 属于 Core；Web 的运行与维护进程见第 12 节。



```mermaid
graph TB
    subgraph User["👤 用户入口"]
        CLI["CLI<br/>click 命令行"]
        API["Python API<br/>fill / connect / preview"]
        YAML["YAML/JSON<br/>配置文件"]
        MCP["MCP 服务器<br/>AI 助手交互"]
    end

    subgraph Core["🧠 核心编排层 (core/)"]
        Orch["DataOrchestrator<br/>主编排引擎"]
        Mapper["ColumnMapper<br/>9 级策略链"]
        Schema["SchemaInferrer<br/>Schema 推断"]
        Relation["RelationResolver<br/>外键解析"]
        Pool["SharedPool<br/>跨表值池"]
        DAG["ColumnDAG<br/>列依赖图"]
        Expr["ExpressionEngine<br/>表达式求值"]
        Constraint["ConstraintSolver<br/>约束回溯"]
        Transform["TransformLoader<br/>脚本加载"]
        Result["GenerationResult<br/>结果统计"]
        Stream["DataStream<br/>流式生成"]
        CheckParser["check_parser.py<br/>CHECK 约束解析"]
        SchemaFallback["schema_fallback.py<br/>纯 schema 回退生成器"]
        Features["features.py<br/>规范化结构特征"]
    end

    subgraph Gen["⚡ 数据生成层 (generators/)"]
        Protocol["DataProvider<br/>Protocol"]
        Registry["ProviderRegistry<br/>注册表"]
        Base["BaseProvider<br/>内置"]
        Faker["FakerProvider<br/>Faker"]
        Mimesis["MimesisProvider<br/>Mimesis"]
    end

    subgraph DB["💾 数据库层 (database/)"]
        DBProto["DatabaseAdapter<br/>Protocol"]
        SU["SQLAlchemyAdapter<br/>必选（SQLite/PostgreSQL）"]
        Raw["RawSQLiteAdapter<br/>仅测试"]
        Pragma["PragmaOptimizer<br/>三级优化"]
        Dialect["_dialect.py<br/>方言抽象"]
        TypeNorm["_type_normalizer.py<br/>类型归一化"]
        BulkOpt["_bulk_optimizer.py<br/>批量写入优化"]
        BaseAdapt["_base_adapter.py<br/>共享基类"]
        Helpers["_helpers.py<br/>批量插入辅助"]
    end

    subgraph Plugin["🧩 插件层 (plugins/)"]
        HookSpec["SqlseedHookSpec<br/>12 个 Hook"]
        PM["PluginManager<br/>pluggy"]
    end

    subgraph Config["⚙️ 配置层 (config/)"]
        Models["Pydantic 模型<br/>GeneratorConfig"]
        Loader["Loader<br/>YAML/JSON"]
        Snapshot["SnapshotManager<br/>快照保存/加载"]
    end

    subgraph AI["🤖 AI 插件 (sqlseed-ai)"]
        Analyzer["SchemaAnalyzer<br/>LLM 分析"]
        Refiner["AiConfigRefiner<br/>自纠正闭环"]
        Examples["Few-shot<br/>示例库"]
        Errors["ErrorSummary<br/>错误分类"]
        GemmaModel["GemmaModel<br/>Gemma 4 模型适配器"]
        AIBackend["AIBackend<br/>多后端路由"]
        GemmaTools["GEMMA_TOOLS<br/>原生函数调用"]
    end

    subgraph Utils["🔧 工具层 (_utils/)"]
        SQL["sql_safe<br/>SQL 注入防护"]
        Metrics["MetricsCollector<br/>性能度量"]
        Progress["Progress<br/>多后端：Rich/tqdm/Null"]
        Paths["Paths<br/>平台缓存路径"]
        Logger["Logger<br/>structlog"]
    end

    CLI --> Orch
    API --> Orch
    YAML --> Loader --> Orch
    MCP --> Orch

    Orch --> Schema
    Orch --> Mapper
    Orch --> Relation
    Orch --> DAG
    Orch --> Stream
    Orch --> Pool
    Orch --> Result
    Orch --> PM

    DAG --> Expr
    DAG --> Constraint
    Stream --> Expr
    Stream --> Constraint
    Stream --> Transform
    Stream --> Protocol

    Mapper --> DBProto
    Schema --> DBProto
    Relation --> DBProto
    Relation --> Pool

    Registry --> Base
    Registry --> Faker
    Registry --> Mimesis
    Registry --> Protocol

    DBProto --> SU
    DBProto --> Raw
    SU --> Pragma
    Raw --> Pragma
    SU --> Dialect
    SU --> TypeNorm
    SU --> BulkOpt
    SU --> BaseAdapt
    SU --> Helpers
    Raw --> BaseAdapt
    Raw --> Helpers

    PM --> HookSpec
    PM --> AI

    Analyzer --> Refiner
    Refiner --> Errors
    Analyzer --> Examples
    AIBackend --> GemmaModel
    AIBackend --> Analyzer
    GemmaModel --> GemmaTools

    Orch --> Config

    Orch -.-> SQL
    Orch -.-> Metrics
    Orch -.-> Progress
    Orch -.-> Logger
    SU -.-> SQL
    Raw -.-> SQL
    SU -.-> Helpers
    Raw -.-> Helpers
```

***

## 2. 核心编排流程（fill_table）

下图概括正常执行路径。结构支持预检先于清空和写入；普通 Core 批量执行可能
保留失败前已提交的批次。调用方仍需检查结果中的 `errors` 和 `count`，具体见
[写入与失败语义](maintainable-release.md#write-semantics)。

```mermaid
sequenceDiagram
    participant U as User
    participant O as DataOrchestrator
    participant ST as DataStream (core)
    participant PM as PluginMediator
    participant DB as DatabaseAdapter
    participant P as RelationResolver / SharedPool

    U->>O: fill_table(table, count)
    O->>O: 连接、参数校验与结构支持预检
    opt 启用数据库优化
        O->>DB: optimize_for_bulk_write(count)
    end
    O->>O: _prepare_specs (schema、CHECK、FK、规则与可选 AI)
    O->>ST: _build_stream (seed、表达式、约束)
    loop 按批生成
        O->>ST: generate(count, batch_size)
        ST-->>O: batch
        O->>PM: apply_batch_transforms(table, batch)
        PM-->>O: 最后一个非 None 结果或原 batch
        O->>DB: batch_insert(table, batch)
        DB-->>O: 实际插入数
        O->>O: 记录已完成批次
    end
    O->>DB: restore_settings (finally)
    O->>P: register_shared_pool(table, specs)
    O->>O: 已支持的自引用外键后处理
    O-->>U: GenerationResult (count / errors)
```

***

## 3. ColumnMapper 9 级策略链

```mermaid
flowchart TD
    Start(["map_column(column_info, user_config)"]) --> L1

    L1{"计算列或显式自增主键？"} -->|是| R1["skip"]
    L1 -->|否| L2

    L2{"Level 2<br/>用户配置？"} -->|有| R2["使用用户指定的 generator + params"]
    L2 -->|无| Rowid{"真实 SQLite rowid alias？"}
    Rowid -->|是| R1
    Rowid -->|否| L3

    L3{"Level 3<br/>自定义精确匹配？"} -->|匹配| R3["使用插件注册的精确规则"]
    L3 -->|未匹配| L4

    L4{"Level 4<br/>内置精确匹配？<br/>(<!-- BEGIN:AUTO-GENERATED:exact-match-rule-count -->75<!-- END:AUTO-GENERATED:exact-match-rule-count --> 条规则)"} -->|匹配| R4["email→email<br/>phone→phone<br/>age→integer<br/>city→city<br/>..."]
    L4 -->|未匹配| L5

    L5{"Level 5<br/>有默认值？"} -->|是| R5["skip (跳过生成)<br/>或 __enrich__"]
    L5 -->|否| L6

    L6{"Level 6<br/>自定义模式匹配？"} -->|匹配| R6["使用插件注册的正则规则"]
    L6 -->|未匹配| L7

    L7{"Level 7<br/>内置模式匹配？<br/>(<!-- BEGIN:AUTO-GENERATED:pattern-match-rule-count -->29<!-- END:AUTO-GENERATED:pattern-match-rule-count --> 条正则)"} -->|匹配| R7["*_at→datetime<br/>*_id→foreign_key_or_integer, *_no→string(alnum)<br/>is_*→boolean<br/>..."]
    L7 -->|未匹配| L8

    L8{"Level 8<br/>可 NULL？"} -->|是| R8["skip (跳过生成)<br/>或 __enrich__"]
    L8 -->|否| L9

    L9{"Level 9<br/>类型忠实回退<br/>(32 种 SQL 类型)"} -->|匹配| R9["VARCHAR(32)→max 32 字符<br/>INT8→0~255<br/>BLOB(1024)→1024 字节"]
    L9 -->|未匹配| L10

    L10["默认"] --> R10["string<br/>(min=5, max=50)"]

    R1 --> Done(["返回 GeneratorSpec"])
    R2 --> Done
    R3 --> Done
    R4 --> Done
    R5 --> Done
    R6 --> Done
    R7 --> Done
    R8 --> Done
    R9 --> Done
    R10 --> Done

    style L1 fill:#9C27B0,color:#fff
    style L2 fill:#4CAF50,color:#fff
    style L4 fill:#2196F3,color:#fff
    style L5 fill:#FF9800,color:#fff
    style L7 fill:#2196F3,color:#fff
    style L8 fill:#FF9800,color:#fff
    style L9 fill:#FF9800,color:#fff
    style L10 fill:#9E9E9E,color:#fff
```

***

## 4. Provider 与 Core 流式生成

Provider 与 dispatch 位于 `generators/`；图中的 `DataStream`、表达式和约束
处理器属于 `core/`，由 Core 调用 provider。生成器层不导入 Core。

```mermaid
classDiagram
    class DataProvider {
        <<Protocol>>
        +name: str
        +set_locale(locale: str)
        +set_seed(seed: int)
        +generate(type_name: str, **params) Any
        ... 通过 GENERATOR_MAP 分派到 36 种内部方法
    }

    class BaseProvider {
        -_rng: Random
        -_locale: str
        +name = "base"
        仅类型路由，不生成真实数据
    }

    class FakerProvider {
        -_faker: Faker
        +name = "faker"
        必选核心依赖
    }

    class MimesisProvider {
        -_generic: Generic
        +name = "mimesis"
        可选，高性能
    }

    class ProviderRegistry {
        -_providers: dict
        -_default_name: str
        +register(provider)
        +get(name) DataProvider
        +ensure_provider(name)
        +register_from_entry_points()
    }

    class DataStream {
        -_nodes: list~ColumnNode~
        -_provider: DataProvider
        -_expr_engine: ExpressionEngine
        -_constraint_solver: ConstraintSolver
        -_rng: Random
        +generate(count, batch_size) Iterator
        -_generate_row() dict
        -_apply_generator(spec) Any
    }

    DataProvider <|.. BaseProvider
    DataProvider <|.. FakerProvider
    DataProvider <|.. MimesisProvider
    ProviderRegistry o-- DataProvider
    DataStream --> DataProvider
    DataStream --> ExpressionEngine
    DataStream --> ConstraintSolver
```

***

## 5. 数据库层架构

```mermaid
classDiagram
    class DatabaseAdapter {
        <<Protocol>>
        +connect(db_path: str)
        +close()
        +get_table_names() list~str~
        +get_column_info(table) list~ColumnInfo~
        +get_primary_keys(table) list~str~
        +get_foreign_keys(table) list~ForeignKeyInfo~
        +get_row_count(table) int
        +get_column_values(table, col, limit) list
        +get_index_info(table) list~IndexInfo~
        +get_unique_constraints(table) list~IndexInfo~
        +get_check_constraints(table) list~CheckConstraintInfo~
        +get_sample_rows(table, limit) list~dict~
        +batch_insert(table, data, batch_size) int
        +clear_table(table)
        +optimize_for_bulk_write(expected_rows)
        +restore_settings()
        +execute(sql, params) Any
    }

    class ColumnInfo {
        <<frozen dataclass>>
        +name: str
        +type: str
        +nullable: bool
        +default: Any
        +is_primary_key: bool
        +is_autoincrement: bool
        +is_computed: bool
        +is_rowid_alias: bool | None
    }

    class ForeignKeyInfo {
        <<frozen dataclass>>
        +column: str
        +ref_table: str
        +ref_column: str
        +constraint_id: int | None
        +ref_schema: str | None
    }

    class IndexInfo {
        <<frozen dataclass>>
        +name: str
        +table: str
        +columns: tuple~str~
        +unique: bool
        +is_partial: bool
        +predicate: str | None
    }

    class CheckConstraintInfo {
        <<frozen dataclass>>
        +name: str
        +table: str
        +columns: tuple~str~
        +expression: str
    }

    class SQLAlchemyAdapter {
        -_db: Database
        -_optimizer: PragmaOptimizer
        必选核心依赖
        使用 SQLAlchemy
    }

    class RawSQLiteAdapter {
        -_conn: Connection
        -_optimizer: PragmaOptimizer
        仅测试回退
        使用 sqlite3
    }

    class PragmaOptimizer {
        -_original: PragmaProfile
        +preserve()
        +optimize(expected_rows)
        +restore()
        -_apply_light()
        -_apply_moderate()
        -_apply_aggressive()
    }

    DatabaseAdapter <|.. SQLAlchemyAdapter
    DatabaseAdapter <|.. RawSQLiteAdapter
    SQLAlchemyAdapter --> PragmaOptimizer
    RawSQLiteAdapter --> PragmaOptimizer
    DatabaseAdapter --> ColumnInfo
    DatabaseAdapter --> ForeignKeyInfo
    DatabaseAdapter --> IndexInfo
    DatabaseAdapter --> CheckConstraintInfo
```

***

adapter 明确报告 `ColumnInfo.is_rowid_alias`，默认 `None` 兼容旧构造。SQLite 区分真实 rowid 别名与显式 AUTOINCREMENT，并保留普通主键的可空语义。`IndexInfo.is_partial` 防止将条件唯一性误当作无条件 UNIQUE；SQLAlchemy 在 `predicate` 保留反射出的 WHERE SQL，RawSQLite 可不提供条件原文。谓词由数据库在写入时执行。FK 元数据保留表内约束身份和反射出的父 schema。

## 6. 列依赖 DAG 与约束回溯

```mermaid
flowchart LR
    subgraph DAG["ColumnDAG 拓扑排序"]
        project_no["project_no<br/>pattern: PRJ-\\d{6}<br/>unique: true"]
        short_code_node["short_code<br/>derive_from: project_no<br/>expression: value[-6:]<br/>unique: true"]
        region_code["region_code<br/>derive_from: project_no<br/>expression: value[-4:]"]
        member_no["member_no<br/>pattern: M-\\d{4}<br/>unique: true"]
    end

    project_no --> short_code_node
    project_no --> region_code

    subgraph Backtrack["约束求解 (回溯)"]
        direction TB
        Gen1["生成 project_no = PRJ-004231"]
        Derive1["计算 short_code = 004231"]
        Check1{"short_code<br/>唯一？"}
        Success["✅ 注册成功"]
        Fail["❌ 已存在"]
        BT["🔄 回溯：撤销 project_no<br/>重新生成"]

        Gen1 --> Derive1 --> Check1
        Check1 -->|是| Success
        Check1 -->|否| Fail --> BT --> Gen1
    end
```

***

## 7. AI 插件架构

AI 插件保留不同职责的入口。单表 `ai-suggest` 使用 `SchemaAnalyzer` 与
`AiConfigRefiner`；`ai-analyze` 默认使用 `AutoHealOrchestrator`，`auto-heal`
修复已有配置。共享构造入口 `sqlseed_ai.runtime` 负责配置、客户端和修复编排器，
终端输出与退出码留在 CLI。Web 通过 Python 服务提供待审阅的规则建议。

```mermaid
flowchart TB
    Suggest["ai-suggest / AI hooks / AI MCP"] --> Analyzer[SchemaAnalyzer]
    Analyzer --> Refiner["AiConfigRefiner: 校验与有限重试"]
    Analyze["ai-analyze / auto-heal"] --> Runtime[sqlseed_ai.runtime]
    Runtime --> AutoHeal[AutoHealOrchestrator]
    AutoHeal --> Contracts["规则契约、校验与修复"]
    Web["Web AI 配置助手"] --> Services["AI Python 服务"]
    Refiner --> Rules["YAML 规则 / 分析结果"]
    Contracts --> Rules
    Services --> Review["用户审阅建议"]
    Review --> Rules
    Rules --> Core["离线 Core: 显式预览或执行"]
```

`ai-suggest --auto-heal` 选择完整修复流程，并处理所有表。
AI MCP 的 `sqlseed_gemma4_agent_fill` 是分析后执行的独立入口；普通分析命令
与 Web 建议不因此自动写入数据库。真实模型可达性、输出质量和支持范围须单独验证。

***

## 8. 插件 Hook 生命周期

```mermaid
flowchart TB
    Start(["DataOrchestrator 启动"]) --> Connect

    Connect["_ensure_connected()"]
    Connect --> H1["🔌 sqlseed_register_providers"]
    Connect --> H2["🔌 sqlseed_register_column_mappers"]

    H1 --> Fill["fill_table()"]
    H2 --> Fill

    Fill --> Mapping["列映射"]
    Mapping --> Mediation["sqlseed_apply_ai_suggestions<br/>(firstresult, optional AI plugin)"]
    Mediation --> H3["🤖 sqlseed_ai_analyze_table<br/>(firstresult)"]

    H3 --> Template["模板池"]
    Template --> H4["🤖 sqlseed_pre_generate_templates<br/>(firstresult)"]

    H4 --> H5["📢 sqlseed_before_generate"]

    H5 --> BatchLoop

    subgraph BatchLoop["批次循环"]
        direction TB
        GenBatch["DataStream 生成一批"]
        H6["🔄 sqlseed_transform_row<br/>(每行，热路径)"]
        H7["🔄 sqlseed_transform_batch<br/>(同批输入；最后一个非 None 结果)"]
        H8["📢 sqlseed_before_insert"]
        Insert["batch_insert()"]
        H9["📢 sqlseed_after_insert"]

        GenBatch --> H6 --> H7 --> H8 --> Insert --> H9
    end

    BatchLoop --> H10["📢 sqlseed_after_generate"]

    H10 --> RegisterPool["RelationResolver.register_shared_pool()"]
    RegisterPool --> H11["📢 sqlseed_shared_pool_loaded"]

    H11 --> Done(["返回 GenerationResult"])

    style H3 fill:#FF9800,color:#fff
    style H4 fill:#FF9800,color:#fff
    style H6 fill:#F44336,color:#fff
```

***

## 9. 配置模型层次结构

源列的 `params` 接受映射；省略或填写 `null` 时保留空参数行为。字符串、列表等
非映射值会在配置加载时明确拒绝，不会静默丢弃规则。顶层生成器参数仍覆盖嵌套
`params` 中的同名参数。

```mermaid
classDiagram
    class GeneratorConfig {
        +db_path: str | None
        +url: str | None
        +provider: ProviderType = MIMESIS
        +locale: str = "en_US"
        +tables: list~TableConfig~
        +associations: list~ColumnAssociation~
        +custom_column_mappings: CustomColumnMappings | None
        +optimize_pragma: bool = True
        +snapshot_dir: str | None
        +log_level: str | None (已废弃)
    }

    class TableConfig {
        +name: str
        +count: int = 1000
        +batch_size: int = 5000
        +columns: list~ColumnConfig~
        +clear_before: bool = False
        +seed: int | None
        +transform: str | None
        +enrich: bool = False
    }

    class ColumnConfig {
        +name: str
        --- 源列模式 ---
        +generator: str | None
        +provider: ProviderType | None
        +params: dict
        +null_ratio: float = 0.0
        --- 派生列模式 ---
        +derive_from: str | list~str~ | None
        +expression: str | None
        --- 约束 ---
        +constraints: ColumnConstraintsConfig | None
        --- 原生方法覆盖 ---
        +faker_method: str | None
        +mimesis_method: str | None
        +native_params: dict
        +validate_column_mode() ⚠️ 互斥
    }

    class ColumnConstraintsConfig {
        +unique: bool = False
        +min_value: number | None
        +max_value: number | None
        +regex: str | None
        +max_retries: int = 100 (ge=0)
    }

    class ColumnAssociation {
        +column_name: str
        +source_table: str
        +source_column: str | None = None
        +target_tables: list~str~
        +strategy: Literal["shared_pool", "random"] = "shared_pool"
    }

    class ProviderType {
        <<enum>>
        BASE
        FAKER
        MIMESIS
        CUSTOM
    }

    GeneratorConfig o-- TableConfig
    GeneratorConfig o-- ColumnAssociation
    GeneratorConfig --> ProviderType
    TableConfig o-- ColumnConfig
    ColumnConfig o-- ColumnConstraintsConfig
    ColumnConfig --> ProviderType
```

***

## 10. MCP 服务器架构

```mermaid
flowchart LR
    subgraph Client["AI 助手 (Claude/Cursor/...)"]
        Request["MCP 请求"]
    end

    subgraph MCPServer["mcp-server-sqlseed (FastMCP)——核心，规则驱动，无 LLM"]
        Tool2["🤖 sqlseed_generate_yaml<br/>规则驱动（ColumnMapper）→ YAML"]
        Tool3["⚡ sqlseed_execute_fill<br/>执行数据生成"]
    end

    subgraph AIMCP["sqlseed-ai[mcp] (FastMCP)——AI，LLM 驱动"]
        ToolAI["🤖 sqlseed_ai_generate_yaml<br/>AI 分析 → 自纠正 → YAML"]
        Tool4["💎 sqlseed_gemma4_analyze<br/>Gemma 4 原生函数调用分析"]
        Tool5["💎 sqlseed_gemma4_agent_fill<br/>Gemma 4 Agent 驱动数据填充"]
        Tool6["💎 sqlseed_list_gemma_models<br/>列出可用 Gemma 4 模型"]
    end

    subgraph SQLSeed["sqlseed 核心"]
        Orchestrator["DataOrchestrator"]
        SchemaCtx["get_schema_context()"]
        Mapper["ColumnMapper"]
    end

    subgraph AIPlugin["sqlseed-ai"]
        SA["SchemaAnalyzer"]
        ACR["AiConfigRefiner"]
    end

    Request --> Tool2
    Request --> Tool3
    Request --> ToolAI
    Request --> Tool4
    Request --> Tool5
    Request --> Tool6

    Tool2 --> Mapper
    Tool3 --> Orchestrator
    ToolAI --> SA --> ACR
    Tool4 --> SA
    Tool5 --> Orchestrator
    Tool6 --> SA

    SchemaCtx --> Orchestrator
```

***

## 11. Gemma 4 工具调用协议

以下流程属于 `SchemaAnalyzer` 的结构化响应路径。`AIConfig` 根据后端解析
`gemma4`、`openai` 或 `none` 协议；工具调用返回值供本地解析与校验。
这里没有自动注册任意 Core 工具、执行工具后回注 `tool_result` 的多轮执行循环。

```mermaid
flowchart TD
    Context["表结构与生成规则提示"] --> Protocol["resolve_tool_calling_protocol"]
    Protocol -->|gemma4 / openai| Request["GEMMA_TOOLS + tool_choice auto"]
    Request --> Response["analyze_schema 参数或文本响应"]
    Response --> Parse["JSON 解析与本地校验"]
    Request -->|不支持工具调用| Fallback["云端 JSON mode / 本地 text mode"]
    Protocol -->|none| Fallback
    Fallback --> Parse
    Parse --> Result["分析结果或明确错误"]
```

协议和后端限制见 [Gemma 4 集成](gemma4-integration.zh-CN.md)。后端服务当前
是否提供某个模型，由实际服务决定；项目中的模型注册表不构成可用性保证。

## 12. Web 工作台与组件生命周期

当前项目包含 Core、CLI、AI、MCP 和 Web 五个发行包。Web 直接调用离线 core；模型建议仅在用户请求时通过可选 AI 包生成，确认后的规则可离线执行。supervisor 在组件变更时协调业务和维护进程，避免对正在导入或执行的包直接修改。可用性同时检查发行包与导入结果；卸载后保留配置并说明受影响功能。详见 [Web 指南](web-workbench.md) 和 [支持范围](maintainable-release.md)。

```mermaid
flowchart LR
    Browser[Browser workbench] --> HTTP[FastAPI / Web state]
    HTTP --> Runtime[Web runtime]
    Runtime --> Core[Offline Python core]
    HTTP -. optional suggestions .-> AI[AI Python services]
    Supervisor[Supervisor] --> HTTP
    Supervisor --> Maintenance[Package maintenance worker]
```
