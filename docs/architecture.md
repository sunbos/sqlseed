# sqlseed 架构图

> 本文档使用 Mermaid 图表可视化 sqlseed 的整体架构和各模块内部结构。

---

## 1. 整体系统架构

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
        Mapper["ColumnMapper<br/>8 级策略链"]
        Schema["SchemaInferrer<br/>Schema 推断"]
        Relation["RelationResolver<br/>外键解析"]
        Pool["SharedPool<br/>跨表值池"]
        DAG["ColumnDAG<br/>列依赖图"]
        Expr["ExpressionEngine<br/>表达式求值"]
        Constraint["ConstraintSolver<br/>约束回溯"]
        Transform["TransformLoader<br/>脚本加载"]
        Result["GenerationResult<br/>结果统计"]
    end

    subgraph Gen["⚡ 数据生成层 (generators/)"]
        Protocol["DataProvider<br/>Protocol"]
        Registry["ProviderRegistry<br/>注册表"]
        Base["BaseProvider<br/>内置"]
        Faker["FakerProvider<br/>Faker"]
        Mimesis["MimesisProvider<br/>Mimesis"]
        Stream["DataStream<br/>流式生成"]
    end

    subgraph DB["💾 数据库层 (database/)"]
        DBProto["DatabaseAdapter<br/>Protocol"]
        SU["SQLiteUtilsAdapter<br/>默认"]
        Raw["RawSQLiteAdapter<br/>回退"]
        Pragma["PragmaOptimizer<br/>三级优化"]
    end

    subgraph Plugin["🧩 插件层 (plugins/)"]
        HookSpec["SqlseedHookSpec<br/>11 个 Hook"]
        PM["PluginManager<br/>pluggy"]
    end

    subgraph Config["⚙️ 配置层 (config/)"]
        Models["Pydantic 模型<br/>GeneratorConfig"]
        Loader["Loader<br/>YAML/JSON"]
        Snapshot["SnapshotManager<br/>快照回放"]
    end

    subgraph AI["🤖 AI 插件 (sqlseed-ai)"]
        Analyzer["SchemaAnalyzer<br/>LLM 分析"]
        Refiner["AiConfigRefiner<br/>自纠正闭环"]
        Examples["Few-shot<br/>示例库"]
        Errors["ErrorSummary<br/>错误分类"]
    end

    subgraph Utils["🔧 工具层 (_utils/)"]
        SQL["sql_safe<br/>SQL 注入防护"]
        Helpers["schema_helpers<br/>AUTOINCREMENT"]
        Metrics["MetricsCollector<br/>性能度量"]
        Progress["Progress<br/>Rich 进度条"]
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

    PM --> HookSpec
    PM --> AI

    Analyzer --> Refiner
    Refiner --> Errors
    Analyzer --> Examples

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

---

## 2. 核心编排流程（fill_table 执行链路）

```mermaid
sequenceDiagram
    participant U as 用户
    participant O as DataOrchestrator
    participant S as SchemaInferrer
    participant M as ColumnMapper
    participant R as RelationResolver
    participant AI as AI Plugin (Hook)
    participant D as ColumnDAG
    participant ST as DataStream
    participant DB as DatabaseAdapter
    participant P as SharedPool

    U->>O: fill_table(table, count)
    O->>O: _ensure_connected()
    O->>DB: optimize_for_bulk_write(count)
    O->>S: get_column_info(table)
    S-->>O: list[ColumnInfo]

    O->>M: map_columns(columns, user_configs)
    M-->>O: dict[str, GeneratorSpec]

    O->>R: _resolve_foreign_keys(table, specs)
    R->>DB: get_column_values(ref_table, ref_col)
    R-->>O: specs (with FK values)

    O->>O: _resolve_implicit_associations(SharedPool)

    O->>AI: sqlseed_ai_analyze_table(...)
    AI-->>O: AI suggestions (optional)

    O->>AI: sqlseed_pre_generate_templates(...)
    AI-->>O: template values (optional)

    O->>D: build(specs, column_configs)
    D->>D: topological_sort()
    D-->>O: list[ColumnNode]

    loop 逐批生成
        O->>ST: generate(count, batch_size)
        ST->>ST: _generate_row() × batch_size
        Note over ST: 表达式求值 + 约束检查 + 回溯
        ST-->>O: list[dict] (batch)

        O->>O: _apply_batch_transforms(batch)
        O->>DB: batch_insert(table, batch)
    end

    O->>P: _register_shared_pool(table, specs)
    O-->>U: GenerationResult
```

---

## 3. ColumnMapper 8 级策略链

```mermaid
flowchart TD
    Start(["map_column(column_info, user_config)"]) --> L1

    L1{"Level 1<br/>用户配置？"} -->|有| R1["使用用户指定的 generator + params"]
    L1 -->|无| L2

    L2{"Level 2<br/>自定义精确匹配？"} -->|匹配| R2["使用插件注册的精确规则"]
    L2 -->|未匹配| L3

    L3{"Level 3<br/>内置精确匹配？<br/>(68 条规则)"} -->|匹配| R3["email→email<br/>phone→phone<br/>age→integer<br/>..."]
    L3 -->|未匹配| L4

    L4{"Level 4<br/>自定义模式匹配？"} -->|匹配| R4["使用插件注册的正则规则"]
    L4 -->|未匹配| L5

    L5{"Level 5<br/>内置模式匹配？<br/>(25 条正则)"} -->|匹配| R5["*_at→datetime<br/>*_id→foreign_key<br/>is_*→boolean<br/>..."]
    L5 -->|未匹配| L6

    L6{"Level 6<br/>有默认值<br/>或可 NULL？"} -->|是| R6["skip (跳过生成)"]
    L6 -->|否| L7

    L7{"Level 7<br/>类型忠实回退<br/>(22 种 SQL 类型)"} -->|匹配| R7["VARCHAR(32)→max 32 字符<br/>INT8→0~255<br/>BLOB(1024)→1024 字节"]
    L7 -->|未匹配| L8

    L8["Level 8<br/>默认"] --> R8["string<br/>(min=5, max=50)"]

    R1 --> Done(["返回 GeneratorSpec"])
    R2 --> Done
    R3 --> Done
    R4 --> Done
    R5 --> Done
    R6 --> Done
    R7 --> Done
    R8 --> Done

    style L1 fill:#4CAF50,color:#fff
    style L3 fill:#2196F3,color:#fff
    style L5 fill:#2196F3,color:#fff
    style L7 fill:#FF9800,color:#fff
    style L8 fill:#9E9E9E,color:#fff
```

---

## 4. 数据生成层架构

```mermaid
classDiagram
    class DataProvider {
        <<Protocol>>
        +name: str
        +set_locale(locale: str)
        +set_seed(seed: int)
        +generate(type_name: str, **params) Any
        +set_locale(locale: str) None
        +set_seed(seed: int) None
        ... 通过 _GENERATOR_MAP 分派到 24 种内部方法
    }

    class BaseProvider {
        -_rng: Random
        -_locale: str
        +name = "base"
        零外部依赖
    }

    class FakerProvider {
        -_faker: Faker
        +name = "faker"
        延迟导入 faker
    }

    class MimesisProvider {
        -_generic: Generic
        +name = "mimesis"
        地区映射 en_US→en
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

---

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
        +get_sample_rows(table, limit) list~dict~
        +batch_insert(table, data, batch_size) int
        +clear_table(table)
        +optimize_for_bulk_write(expected_rows)
        +restore_settings()
    }

    class ColumnInfo {
        <<frozen dataclass>>
        +name: str
        +type: str
        +nullable: bool
        +default: Any
        +is_primary_key: bool
        +is_autoincrement: bool
    }

    class ForeignKeyInfo {
        <<frozen dataclass>>
        +column: str
        +ref_table: str
        +ref_column: str
    }

    class IndexInfo {
        <<frozen dataclass>>
        +name: str
        +table: str
        +columns: list~str~
        +unique: bool
    }

    class SQLiteUtilsAdapter {
        -_db: Database
        -_optimizer: PragmaOptimizer
        使用 sqlite-utils
    }

    class RawSQLiteAdapter {
        -_conn: Connection
        -_optimizer: PragmaOptimizer
        使用 sqlite3 (回退)
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

    DatabaseAdapter <|.. SQLiteUtilsAdapter
    DatabaseAdapter <|.. RawSQLiteAdapter
    SQLiteUtilsAdapter --> PragmaOptimizer
    RawSQLiteAdapter --> PragmaOptimizer
    DatabaseAdapter --> ColumnInfo
    DatabaseAdapter --> ForeignKeyInfo
    DatabaseAdapter --> IndexInfo
```

---

## 6. 列依赖 DAG 与约束回溯

```mermaid
flowchart LR
    subgraph DAG["ColumnDAG 拓扑排序"]
        card_number["card_number<br/>pattern: 62[0-9]{17}<br/>unique: true"]
        CutCard4["last_eight<br/>derive_from: card_number<br/>expression: value[-8:]<br/>unique: true"]
        CutCard3["last_six<br/>derive_from: card_number<br/>expression: value[-6:]"]
        account_id["account_id<br/>pattern: U[0-9]{10}<br/>unique: true"]
    end

    card_number --> CutCard4
    card_number --> CutCard3

    subgraph Backtrack["约束求解 (回溯)"]
        direction TB
        Gen1["生成 card_number = 6200001234567890123"]
        Derive1["计算 last_eight = 67890123"]
        Check1{"last_eight<br/>唯一？"}
        Success["✅ 注册成功"]
        Fail["❌ 已存在"]
        BT["🔄 回溯：撤销 card_number<br/>重新生成"]

        Gen1 --> Derive1 --> Check1
        Check1 -->|是| Success
        Check1 -->|否| Fail --> BT --> Gen1
    end
```

---

## 7. AI 插件架构

```mermaid
flowchart TB
    subgraph CLI_Trigger["触发入口"]
        CLICmd["sqlseed ai-suggest"]
        HookCall["sqlseed_ai_analyze_table Hook"]
        MCPTool["MCP: sqlseed_generate_yaml"]
    end

    subgraph Analyzer["SchemaAnalyzer"]
        Context["构建上下文<br/>列 + 索引 + FK + 样本 + 分布"]
        FewShot["注入 Few-shot 示例<br/>(4 个典型场景)"]
        SysPrompt["System Prompt<br/>生成器列表 + 输出格式"]
        LLM["调用 LLM<br/>OpenAI 兼容 API<br/>response_format: json_object"]
    end

    subgraph Refiner["AiConfigRefiner 自纠正闭环"]
        direction TB
        Init["初始生成"]
        Validate["验证配置"]
        VCheck{"通过？"}
        Cache["缓存结果<br/>(schema hash 校验)"]
        ErrorSum["ErrorSummary<br/>错误分类"]
        FixPrompt["构建修正 Prompt"]
        Retry["重试 LLM"]
        MaxCheck{"超过<br/>max_retries?"}
        FailErr["AISuggestionFailedError"]

        Init --> Validate --> VCheck
        VCheck -->|✅| Cache
        VCheck -->|❌| ErrorSum --> FixPrompt --> Retry
        Retry --> Validate
        MaxCheck -->|是| FailErr
    end

    subgraph Validation["验证步骤"]
        V1["1. Pydantic TableConfig 解析"]
        V2["2. 列名存在性检查"]
        V3["3. 空配置检查"]
        V4["4. preview_table(count=5) 试运行"]
    end

    subgraph ErrorTypes["错误类型"]
        E1["pydantic_validation"]
        E2["json_syntax"]
        E3["unknown_generator"]
        E4["expression_error"]
        E5["column_mismatch"]
        E6["empty_config"]
        E7["fatal (不可重试)"]
    end

    CLICmd --> Analyzer
    HookCall --> Analyzer
    MCPTool --> Analyzer

    Context --> FewShot --> SysPrompt --> LLM
    LLM --> Refiner

    Validate --> Validation
    ErrorSum --> ErrorTypes

    style Cache fill:#4CAF50,color:#fff
    style FailErr fill:#F44336,color:#fff
```

---

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
    Mapping --> H3["🤖 sqlseed_ai_analyze_table<br/>(firstresult)"]

    H3 --> Template["模板池"]
    Template --> H4["🤖 sqlseed_pre_generate_templates<br/>(firstresult)"]

    H4 --> H5["📢 sqlseed_before_generate"]

    H5 --> BatchLoop

    subgraph BatchLoop["批次循环"]
        direction TB
        GenBatch["DataStream 生成一批"]
        H6["🔄 sqlseed_transform_row<br/>(每行，热路径)"]
        H7["🔄 sqlseed_transform_batch<br/>(链式处理)"]
        H8["📢 sqlseed_before_insert"]
        Insert["batch_insert()"]
        H9["📢 sqlseed_after_insert"]

        GenBatch --> H6 --> H7 --> H8 --> Insert --> H9
    end

    BatchLoop --> H10["📢 sqlseed_after_generate"]

    H10 --> RegisterPool["_register_shared_pool()"]
    RegisterPool --> H11["📢 sqlseed_shared_pool_loaded"]

    H11 --> Done(["返回 GenerationResult"])

    style H3 fill:#FF9800,color:#fff
    style H4 fill:#FF9800,color:#fff
    style H6 fill:#F44336,color:#fff
```

---

## 9. 配置模型层次结构

```mermaid
classDiagram
    class GeneratorConfig {
        +db_path: str
        +provider: ProviderType = MIMESIS
        +locale: str = "en_US"
        +tables: list~TableConfig~
        +associations: list~ColumnAssociation~
        +optimize_pragma: bool = True
        +log_level: str = "INFO"
        +snapshot_dir: str | None
    }

    class TableConfig {
        +name: str
        +count: int = 1000
        +batch_size: int = 5000
        +columns: list~ColumnConfig~
        +clear_before: bool = False
        +seed: int | None
        +transform: str | None
    }

    class ColumnConfig {
        +name: str
        --- 源列模式 ---
        +generator: str | None
        +provider: ProviderType | None
        +params: dict
        +null_ratio: float = 0.0
        --- 派生列模式 ---
        +derive_from: str | None
        +expression: str | None
        --- 约束 ---
        +constraints: ColumnConstraintsConfig | None
        +validate_column_mode() ⚠️ 互斥
    }

    class ColumnConstraintsConfig {
        +unique: bool = False
        +min_value: number | None
        +max_value: number | None
        +regex: str | None
        +max_retries: int = 100
    }

    class ColumnAssociation {
        +column_name: str
        +source_table: str
        +target_tables: list~str~
        +strategy: str = "shared_pool"
    }

    class ProviderType {
        <<enum>>
        BASE
        FAKER
        MIMESIS
        CUSTOM
        AI
    }

    GeneratorConfig o-- TableConfig
    GeneratorConfig o-- ColumnAssociation
    GeneratorConfig --> ProviderType
    TableConfig o-- ColumnConfig
    ColumnConfig o-- ColumnConstraintsConfig
    ColumnConfig --> ProviderType
```

---

## 10. MCP 服务器架构

```mermaid
flowchart LR
    subgraph Client["AI 助手 (Claude/Cursor/...)"]
        Request["MCP 请求"]
    end

    subgraph MCPServer["mcp-server-sqlseed (FastMCP)"]
        Resource["📖 Resource<br/>sqlseed://schema/{db}/{table}"]
        Tool1["🔍 sqlseed_inspect_schema<br/>返回: 列 + FK + 索引 + 样本 + hash"]
        Tool2["🤖 sqlseed_generate_yaml<br/>AI 分析 → 自纠正 → YAML"]
        Tool3["⚡ sqlseed_execute_fill<br/>执行数据生成"]
    end

    subgraph SQLSeed["sqlseed 核心"]
        Orchestrator["DataOrchestrator"]
        SchemaCtx["get_schema_context()"]
    end

    subgraph AIPlugin["sqlseed-ai"]
        SA["SchemaAnalyzer"]
        ACR["AiConfigRefiner"]
    end

    Request --> Resource
    Request --> Tool1
    Request --> Tool2
    Request --> Tool3

    Resource --> SchemaCtx
    Tool1 --> SchemaCtx
    Tool2 --> SA --> ACR
    Tool3 --> Orchestrator

    SchemaCtx --> Orchestrator
```
