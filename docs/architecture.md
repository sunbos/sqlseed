# sqlseed Architecture

**[English](architecture.md)** | [中文](architecture.zh-CN.md)

> This document uses Mermaid diagrams to visualize sqlseed's overall architecture and internal module structures.

---

## 1. System Architecture

```mermaid
graph TB
    subgraph User["👤 User Entry Points"]
        CLI["CLI<br/>click commands"]
        API["Python API<br/>fill / connect / preview"]
        YAML["YAML/JSON<br/>config files"]
        MCP["MCP Server<br/>AI assistant integration"]
    end

    subgraph Core["🧠 Core Orchestration (core/)"]
        Orch["DataOrchestrator<br/>main orchestrator"]
        Mapper["ColumnMapper<br/>9-level strategy chain"]
        Schema["SchemaInferrer<br/>schema inference"]
        Relation["RelationResolver<br/>FK resolution"]
        Pool["SharedPool<br/>cross-table value pool"]
        DAG["ColumnDAG<br/>column dependency graph"]
        Expr["ExpressionEngine<br/>expression evaluation"]
        Constraint["ConstraintSolver<br/>constraint backtracking"]
        Transform["TransformLoader<br/>script loading"]
        Result["GenerationResult<br/>result statistics"]
    end

    subgraph Gen["⚡ Generator Layer (generators/)"]
        Protocol["DataProvider<br/>Protocol"]
        Registry["ProviderRegistry<br/>registry"]
        Base["BaseProvider<br/>built-in"]
        Faker["FakerProvider<br/>Faker"]
        Mimesis["MimesisProvider<br/>Mimesis"]
        Stream["DataStream<br/>streaming generation"]
    end

    subgraph DB["💾 Database Layer (database/)"]
        DBProto["DatabaseAdapter<br/>Protocol"]
        SU["SQLAlchemyAdapter<br/>required"]
        Raw["RawSQLiteAdapter<br/>test-only"]
        Pragma["PragmaOptimizer<br/>3-tier optimization"]
        Dialect["_dialect.py<br/>dialect abstraction"]
        TypeNorm["_type_normalizer.py<br/>type normalization"]
        BulkOpt["_bulk_optimizer.py<br/>bulk write optimization"]
        BaseAdapt["_base_adapter.py<br/>shared base"]
        Helpers["_helpers.py<br/>batch insert helpers"]
    end

    subgraph Plugin["🧩 Plugin Layer (plugins/)"]
        HookSpec["SqlseedHookSpec<br/>12 hooks"]
        PM["PluginManager<br/>pluggy"]
    end

    subgraph Config["⚙️ Config Layer (config/)"]
        Models["Pydantic Models<br/>GeneratorConfig"]
        Loader["Loader<br/>YAML/JSON"]
        Snapshot["SnapshotManager<br/>snapshot save/load"]
    end

    subgraph AI["🤖 AI Plugin (sqlseed-ai)"]
        Analyzer["SchemaAnalyzer<br/>LLM analysis"]
        Refiner["AiConfigRefiner<br/>self-correction loop"]
        Examples["Few-shot<br/>example library"]
        Errors["ErrorSummary<br/>error classification"]
        GemmaModel["GemmaModel<br/>Gemma 4 model adapter"]
        AIBackend["AIBackend<br/>multi-backend router"]
        GemmaTools["GEMMA_TOOLS<br/>Native Function Calling"]
    end

    subgraph Utils["🔧 Utilities (_utils/)"]
        SQL["sql_safe<br/>SQL injection protection"]
        Helpers["schema_helpers<br/>AUTOINCREMENT"]
        Metrics["MetricsCollector<br/>performance metrics"]
        Progress["Progress<br/>multi-backend: Rich/tqdm/Null"]
        Paths["Paths<br/>platform cache dirs"]
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

---

## 2. Core Orchestration Flow (fill_table Execution)

```mermaid
sequenceDiagram
    participant U as User
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

    loop Batch Generation
        O->>ST: generate(count, batch_size)
        ST->>ST: _generate_row() × batch_size
        Note over ST: Expression eval + constraint check + backtrack
        ST-->>O: list[dict] (batch)

        O->>O: _apply_batch_transforms(batch)
        O->>DB: batch_insert(table, batch)
    end

    O->>P: _register_shared_pool(table, specs)
    O-->>U: GenerationResult
```

---

## 3. ColumnMapper 9-Level Strategy Chain

```mermaid
flowchart TD
    Start(["map_column(column_info, user_config)"]) --> L1

    L1{"Level 1<br/>Autoincrement PK?<br/>PK + AUTOINCREMENT"} -->|Yes| R1["skip"]
    L1 -->|No| L2

    L2{"Level 2<br/>User config?"} -->|Yes| R2["Use user-specified generator + params"]
    L2 -->|No| L3

    L3{"Level 3<br/>Custom exact match?"} -->|Match| R3["Use plugin-registered exact rules"]
    L3 -->|No match| L4

    L4{"Level 4<br/>Built-in exact match?<br/>(<!-- BEGIN:AUTO-GENERATED:exact-match-rule-count -->75<!-- END:AUTO-GENERATED:exact-match-rule-count --> rules)"} -->|Match| R4["email→email<br/>phone→phone<br/>age→integer<br/>city→city<br/>..."]
    L4 -->|No match| L5

    L5{"Level 5<br/>Has DEFAULT?"} -->|Yes| R5["skip (skip generation)<br/>or __enrich__"]
    L5 -->|No| L6

    L6{"Level 6<br/>Custom pattern match?"} -->|Match| R6["Use plugin-registered regex rules"]
    L6 -->|No match| L7

    L7{"Level 7<br/>Built-in pattern match?<br/>(<!-- BEGIN:AUTO-GENERATED:pattern-match-rule-count -->29<!-- END:AUTO-GENERATED:pattern-match-rule-count --> regexes)"} -->|Match| R7["*_at→datetime<br/>*_id / *_no→foreign_key_or_integer<br/>is_*→boolean<br/>..."]
    L7 -->|No match| L8

    L8{"Level 8<br/>Nullable?"} -->|Yes| R8["skip (skip generation)<br/>or __enrich__"]
    L8 -->|No| L9

    L9{"Level 9<br/>Type-faithful fallback<br/>(22 SQL types)"} -->|Match| R9["VARCHAR(32)→max 32 chars<br/>INT8→0~255<br/>BLOB(1024)→1024 bytes"]
    L9 -->|No match| L10

    L10["Default"] --> R10["string<br/>(min=5, max=50)"]

    R1 --> Done(["Return GeneratorSpec"])
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

---

## 4. Generator Layer Architecture

```mermaid
classDiagram
    class DataProvider {
        <<Protocol>>
        +name: str
        +set_locale(locale: str)
        +set_seed(seed: int)
        +generate(type_name: str, **params) Any
        ... dispatches via GENERATOR_MAP to 31 internal methods
    }

    class BaseProvider {
        -_rng: Random
        -_locale: str
        +name = "base"
        type-routing only, no real data
    }

    class FakerProvider {
        -_faker: Faker
        +name = "faker"
        required core dependency
    }

    class MimesisProvider {
        -_generic: Generic
        +name = "mimesis"
        optional, high-performance
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

## 5. Database Layer Architecture

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
        +columns: tuple~str~
        +unique: bool
    }

    class SQLAlchemyAdapter {
        -_db: Database
        -_optimizer: PragmaOptimizer
        required core dependency
        uses SQLAlchemy
    }

    class RawSQLiteAdapter {
        -_conn: Connection
        -_optimizer: PragmaOptimizer
        test-only fallback
        uses sqlite3
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
```

---

## 6. Column Dependency DAG & Constraint Backtracking

```mermaid
flowchart LR
    subgraph DAG["ColumnDAG Topological Sort"]
        project_no["project_no<br/>pattern: PRJ-\\d{6}<br/>unique: true"]
        short_code_node["short_code<br/>derive_from: project_no<br/>expression: value[-6:]<br/>unique: true"]
        region_code["region_code<br/>derive_from: project_no<br/>expression: value[-4:]"]
        member_no["member_no<br/>pattern: M-\\d{4}<br/>unique: true"]
    end

    project_no --> short_code_node
    project_no --> region_code

    subgraph Backtrack["Constraint Solving (Backtracking)"]
        direction TB
        Gen1["Generate project_no = PRJ-004231"]
        Derive1["Compute short_code = 004231"]
        Check1{"short_code<br/>unique?"}
        Success["✅ Registered"]
        Fail["❌ Already exists"]
        BT["🔄 Backtrack: undo project_no<br/>regenerate"]

        Gen1 --> Derive1 --> Check1
        Check1 -->|Yes| Success
        Check1 -->|No| Fail --> BT --> Gen1
    end
```

---

## 7. AI Plugin Architecture

```mermaid
flowchart TB
    subgraph CLI_Trigger["Entry Points"]
        CLICmd["sqlseed ai-suggest"]
        HookCall["sqlseed_ai_analyze_table Hook"]
        MCPTool["MCP: sqlseed_generate_yaml"]
        MCPGemma4Analyze["MCP: sqlseed_gemma4_analyze"]
        MCPGemma4AgentFill["MCP: sqlseed_gemma4_agent_fill"]
    end

    subgraph Analyzer["SchemaAnalyzer"]
        Context["Build context<br/>columns + indexes + FK + samples + distribution"]
        FewShot["Inject few-shot examples<br/>(4 typical scenarios)"]
        SysPrompt["System Prompt<br/>generator list + output format"]
        LLM["Call LLM<br/>AIBackend multi-backend<br/>OpenAI API / Gemma 4 GEMMA_TOOLS<br/>response_format: json_object"]
    end

    subgraph Refiner["AiConfigRefiner Self-Correction Loop"]
        direction TB
        Init["Initial generation"]
        Validate["Validate config"]
        VCheck{"Pass?"}
        Cache["Cache result<br/>(schema hash validation)"]
        ErrorSum["ErrorSummary<br/>error classification"]
        FixPrompt["Build correction prompt"]
        Retry["Retry LLM"]
        MaxCheck{"Exceeded<br/>max_retries?"}
        FailErr["AISuggestionFailedError"]

        Init --> Validate --> VCheck
        VCheck -->|✅| Cache
        VCheck -->|❌| ErrorSum --> FixPrompt --> Retry
        Retry --> Validate
        MaxCheck -->|Yes| FailErr
    end

    subgraph Validation["Validation Steps"]
        V1["1. Pydantic TableConfig parsing"]
        V2["2. Column name existence check"]
        V3["3. Empty config check"]
        V4["4. preview_table(count=5) dry run"]
    end

    subgraph ErrorTypes["Error Types"]
        E1["pydantic_validation"]
        E2["json_syntax"]
        E3["unknown_generator"]
        E4["expression_error"]
        E5["column_mismatch"]
        E6["empty_config"]
        E7["fatal (non-retryable)"]
    end

    CLICmd --> Analyzer
    HookCall --> Analyzer
    MCPTool --> Analyzer
    MCPGemma4Analyze --> Analyzer
    MCPGemma4AgentFill --> Analyzer

    Context --> FewShot --> SysPrompt --> LLM
    LLM --> Refiner

    Validate --> Validation
    ErrorSum --> ErrorTypes

    style Cache fill:#4CAF50,color:#fff
    style FailErr fill:#F44336,color:#fff
```

---

## 8. Plugin Hook Lifecycle

```mermaid
flowchart TB
    Start(["DataOrchestrator starts"]) --> Connect

    Connect["_ensure_connected()"]
    Connect --> H1["🔌 sqlseed_register_providers"]
    Connect --> H2["🔌 sqlseed_register_column_mappers"]

    H1 --> Fill["fill_table()"]
    H2 --> Fill

    Fill --> Mapping["Column mapping"]
    Mapping --> H3["🤖 sqlseed_ai_analyze_table<br/>(firstresult)"]

    H3 --> Template["Template pool"]
    Template --> H4["🤖 sqlseed_pre_generate_templates<br/>(firstresult)"]

    H4 --> H5["📢 sqlseed_before_generate"]

    H5 --> BatchLoop

    subgraph BatchLoop["Batch Loop"]
        direction TB
        GenBatch["DataStream generates a batch"]
        H6["🔄 sqlseed_transform_row<br/>(per-row, hot path)"]
        H7["🔄 sqlseed_transform_batch<br/>(chained processing)"]
        H8["📢 sqlseed_before_insert"]
        Insert["batch_insert()"]
        H9["📢 sqlseed_after_insert"]

        GenBatch --> H6 --> H7 --> H8 --> Insert --> H9
    end

    BatchLoop --> H10["📢 sqlseed_after_generate"]

    H10 --> RegisterPool["_register_shared_pool()"]
    RegisterPool --> H11["📢 sqlseed_shared_pool_loaded"]

    H11 --> Done(["Return GenerationResult"])

    style H3 fill:#FF9800,color:#fff
    style H4 fill:#FF9800,color:#fff
    style H6 fill:#F44336,color:#fff
```

---

## 9. Config Model Hierarchy

```mermaid
classDiagram
    class GeneratorConfig {
        +db_path: str
        +provider: ProviderType = MIMESIS
        +locale: str = "en_US"
        +tables: list~TableConfig~
        +associations: list~ColumnAssociation~
        +optimize_pragma: bool = True
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
        +enrich: bool = False
    }

    class ColumnConfig {
        +name: str
        --- Source mode ---
        +generator: str | None
        +provider: ProviderType | None
        +params: dict
        +null_ratio: float = 0.0
        --- Derived mode ---
        +derive_from: str | None
        +expression: str | None
        --- Constraints ---
        +constraints: ColumnConstraintsConfig | None
        +validate_column_mode() ⚠️ mutually exclusive
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

---

## 10. MCP Server Architecture

```mermaid
flowchart LR
    subgraph Client["AI Assistant (Claude/Cursor/...)"]
        Request["MCP Request"]
    end

    subgraph MCPServer["mcp-server-sqlseed (FastMCP)"]
        Resource["📖 Resource<br/>sqlseed://schema/{db}/{table}"]
        Tool1["🔍 sqlseed_inspect_schema<br/>Returns: columns + FK + indexes + samples + hash"]
        Tool2["🤖 sqlseed_generate_yaml<br/>AI analysis → self-correction → YAML"]
        Tool3["⚡ sqlseed_execute_fill<br/>Execute data generation"]
        Tool4["💎 sqlseed_gemma4_analyze<br/>Gemma 4 native function calling analysis"]
        Tool5["💎 sqlseed_gemma4_agent_fill<br/>Gemma 4 agent-driven data fill"]
        Tool6["💎 sqlseed_list_gemma_models<br/>List available Gemma 4 models"]
    end

    subgraph SQLSeed["sqlseed Core"]
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
    Request --> Tool4
    Request --> Tool5
    Request --> Tool6

    Resource --> SchemaCtx
    Tool1 --> SchemaCtx
    Tool2 --> SA --> ACR
    Tool3 --> Orchestrator
    Tool4 --> SA
    Tool5 --> Orchestrator
    Tool6 --> SA

    SchemaCtx --> Orchestrator
```

---

## 11. Gemma 4 Integration Architecture

```mermaid
flowchart TB
    subgraph MCPEntry["MCP Tool Entry Points"]
        G4Analyze["💎 sqlseed_gemma4_analyze<br/>Schema analysis via Gemma 4"]
        G4AgentFill["💎 sqlseed_gemma4_agent_fill<br/>Agent-driven data fill"]
        G4List["💎 sqlseed_list_gemma_models<br/>List available Gemma 4 models"]
    end

    subgraph Backend["AIBackend Multi-Backend Router"]
        Router["AIBackend<br/>backend selection"]
        OpenAIBe["OpenAI Backend<br/>chat.completions API"]
        GemmaBe["Gemma 4 Backend<br/>GEMMA_TOOLS Native FC"]
    end

    subgraph GemmaFC["GEMMA_TOOLS Native Function Calling"]
        ToolReg["Tool Registration<br/>auto_register(sqlseed tools)"]
        FCRequest["Function Call Request<br/>model generates tool_call"]
        FCExec["Tool Execution<br/>sqlseed core executes"]
        FCResult["Result Injection<br/>tool_result → conversation"]
        FCIterate["Iterative Refinement<br/>multi-turn tool use"]
    end

    subgraph Core["sqlseed Core Integration"]
        SchemaCtx["get_schema_context()"]
        Orchestrator["DataOrchestrator"]
        Mapper["ColumnMapper"]
    end

    G4Analyze --> Router
    G4AgentFill --> Router
    G4List --> Router

    Router --> OpenAIBe
    Router --> GemmaBe

    GemmaBe --> ToolReg
    ToolReg --> FCRequest
    FCRequest --> FCExec
    FCExec --> FCResult
    FCResult --> FCIterate
    FCIterate --> FCRequest

    FCExec --> SchemaCtx
    FCExec --> Orchestrator
    FCExec --> Mapper

    SchemaCtx --> Orchestrator

    style GemmaBe fill:#4285F4,color:#fff
    style ToolReg fill:#34A853,color:#fff
    style FCRequest fill:#34A853,color:#fff
    style FCExec fill:#FBBC05,color:#000
    style FCResult fill:#34A853,color:#fff
    style FCIterate fill:#EA4335,color:#fff
```
