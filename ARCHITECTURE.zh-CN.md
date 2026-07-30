# sqlseed 项目架构决策

**创建日期：** 2026-06-26
**状态：** 已与用户需求对齐（已应用 Round 6 修订）
**用途：** AI agent（CLAUDE/AGENTS/GEMINI）和贡献者的权威架构参考。所有代码变更必须遵循本文档。

---

## 1. 项目愿景

sqlseed 是一个**声明式多数据库测试数据生成工具包**。它专注于为数据库写入合理的测试数据——不涉及其他功能。

### 核心原则

1. **核心稳定性**：核心包（`sqlseed`）必须保持稳定，不受 AI 或外部技术变化的冲击。外部功能以插件形式演进。
2. **离线优先**：核心功能必须能在离线环境下工作，不依赖外部网络。AI/CLI/MCP 功能是可选插件。
3. **Python API 优先**：核心是一个 Python 库（`from sqlseed import fill`）。CLI 是便捷层，不是核心。
4. **插件架构**：外部功能（CLI、AI、MCP）通过插件连接到核心。用户只安装需要的功能。

### 目标用户

- 测试工程师（使用 CLI：`sqlseed fill app.db -t users -n 1000`）
- 数据库开发者（使用 Python API：`from sqlseed import fill`）
- 数据专员（使用 Python API 进行数据管道处理）

---

## 2. 架构概览

```
                    ┌─────────────────────────────────────────┐
                    │           用户安装选择                    │
                    │  pip install sqlseed              (核心) │
                    │  pip install sqlseed-cli           (CLI) │
                    │  pip install sqlseed-ai             (AI) │
                    │  pip install mcp-server-sqlseed    (MCP) │
                    └────────────────────┬────────────────────┘
                                         │
                    ┌────────────────────▼────────────────────┐
                    │           sqlseed（核心包）               │
                    │  ┌────────────────────────────────────┐ │
                    │  │ Python API: fill, connect, preview │ │
                    │  │ fill_from_config, load_config      │ │
                    │  └────────────────────────────────────┘ │
                    │  ┌──────────┐ ┌──────────┐ ┌──────────┐ │
                    │  │ core/    │ │generators│ │ database/│ │
                    │  │(逻辑)    │ │(数据)    │ │(适配器)  │ │
                    │  └──────────┘ └──────────┘ └──────────┘ │
                    │  ┌──────────┐ ┌──────────┐               │
                    │  │ plugins/ │ │ config/  │               │
                    │  │(hookspec │ │(模型,    │               │
                    │  │+管理器)  │ │ 加载器)  │               │
                    │  └──────────┘ └──────────┘               │
                    │  ┌──────────────────────────────────┐   │
                    │  │ _utils/（无内部依赖）             │   │
                    │  └──────────────────────────────────┘   │
                    └────────────────────┬────────────────────┘
                                         │ pluggy hooks
                    ┌────────────────────▼────────────────────┐
                    │              插件层                      │
                    │                                          │
                    │  ┌─────────────┐  ┌──────────────────┐  │
                    │  │ sqlseed-cli │  │   sqlseed-ai     │  │
                    │  │ (CLI: fill, │  │ (AI YAML 生成,   │  │
                    │  │  preview,   │  │  Gemma4 作为     │  │
                    │  │  inspect,   │  │  长期 LLM 后端   │  │
                    │  │  init,      │  │  via tool_call-  │  │
                    │  │  replay)    │  │  ing_protocol,   │  │
                    │  │             │  │  自我纠错)        │  │
                    │  │             │  │  + 可选 MCP 接口  │  │
                    │  └─────────────┘  └──────────────────┘  │
                    │                                          │
                    │  ┌────────────────────────────────────┐ │
                    │  │ mcp-server-sqlseed                 │ │
                    │  │ (MCP: generate_yaml [规则驱动,     │ │
                    │  │  无 LLM], execute_fill — 仅核心    │ │
                    │  │  能力, 无 schema 检查, 无 AI)      │ │
                    │  └────────────────────────────────────┘ │
                    └──────────────────────────────────────────┘
```

---

## 3. 模块职责

> [!IMPORTANT]
> 以下描述的是重构后（Phase A-G）的**目标架构**。
> 当前代码与目标有差异——参见第 8 节"重构清单"了解差距和执行步骤。
> 此处显示的方法/函数名是**目标名称**；当前代码不同时，在括号中标注当前名称。

### 3.1 核心包（`src/sqlseed/`）

**保留在核心**（离线、稳定、无 CLI/AI 依赖）：

| 模块 | 职责 | 关键类/函数 |
|------|------|-------------|
| `__init__.py` | 公共 Python API | `fill`, `connect`, `preview`, `fill_from_config`, `load_config` |
| `core/orchestrator/` | 中央协调器（4 个 mixin + 共享数据） | `DataOrchestrator` |
| `core/mapper.py` | 9 级列映射策略链 | `ColumnMapper`, `GeneratorSpec` |
| `core/schema.py` | 从数据库推断 schema | `SchemaInferrer` |
| `core/relation.py` | 外键完整性 + 跨表关系 | `RelationResolver`, `SharedPool` |
| `core/column_dag.py` | `derive_from` 依赖的拓扑排序 | `ColumnDAG` |
| `core/expression.py` | `derive_from` 表达式引擎（simpleeval） | `ExpressionEngine` |
| `core/constraints.py` | UNIQUE 约束强制执行（带回溯） | `ConstraintSolver` |
| `core/transform.py` | 行/批次转换管道 | `load_transform()` |
| `core/result.py` | 生成结果数据类 | `GenerationResult` |
| `core/stream.py` | DataStream 批次生成迭代器 | `DataStream` |
| `core/unique_adjuster.py` | 生成后 UNIQUE 调整 | `UniqueAdjuster` |
| `core/plugin_mediator.py` | **仅通用**插件中介（目标：AI 专用 `apply_ai_suggestions()` 移出） | `apply_batch_transforms()`, `apply_template_pool()` |
| `core/enrichment.py` | 枚举检测 + 本地 enrichment（无 AI 逻辑，**整体**保留在核心） | `EnrichmentEngine`（当前：`is_enumeration_column()`, `apply()`） |
| `generators/` | 数据提供者（faker 必需，mimesis 可选） | `FakerProvider`, `MimesisProvider`, `BaseProvider` |
| `database/` | 数据库适配器：SQLAlchemy（必需，SQLite+PostgreSQL） | `SQLAlchemyAdapter`, `RawSQLiteAdapter`（仅测试） |
| `plugins/` | pluggy hookspecs + 管理器（插件基础设施） | `PluginManager`, hookspecs |
| `config/` | Pydantic 模型, YAML 加载器, SnapshotManager | `GeneratorConfig`, `SnapshotManager` |
| `_utils/` | 内部工具（无内部依赖） | `sql_safe`, `logger`, `metrics`, `progress`, `paths` |

**移出核心**（到插件）：

| 当前位置 | 目标位置 | 原因 |
|---------|---------|------|
| `cli/`（整个目录） | `plugins/sqlseed-cli/` | CLI 是可选的，依赖 click/rich |
| `cli/ai_commands.py` | `plugins/sqlseed-ai/` | AI CLI 命令，需要网络 |
| `core/plugin_mediator.py` `apply_ai_suggestions()` | `plugins/sqlseed-ai/` | AI 专用中介 |

**删除**（MySQL 支持）：

| 位置 | 操作 |
|------|------|
| `database/_dialect.py` MySQL 提及（仅注释/文档字符串，**无 `MySQLDialect` 类**） | 清理 |
| `database/_type_normalizer.py` `_MYSQL_TYPE_MAP` + `dialect_name == "mysql"` 分支 | 删除 |
| `database/sqlalchemy_adapter.py` `if "mysql" in db_url` + `if dialect_name == "mysql"` 分支 | 删除 |
| `pyproject.toml` `mysql` 可选依赖 | 删除 |
| 引用 MySQL 的测试/文档 | 删除 |

### 3.2 插件：`sqlseed-cli`（`plugins/sqlseed-cli/`）

| 组件 | 职责 |
|------|------|
| `cli/main.py` | 命令：`fill`, `preview`, `inspect`, `init`, `replay` |
| `cli/_utils.py` | `sanitize_table_config()` 用于 LLM 配置清理 |
| Entry point | `[project.scripts] sqlseed = sqlseed_cli:main` |
| 依赖 | `sqlseed`（核心）, `click`, `rich` |

**安装**：`pip install sqlseed-cli`（完全独立的包，拥有独立 `pyproject.toml`、独立版本号、独立发布）

### 3.3 插件：`sqlseed-ai`（`plugins/sqlseed-ai/`）

| 组件 | 职责 |
|------|------|
| `analyzer/` | LLM 表级分析（流式、工具调用）。包含 `_tool_calling.py`，实现可插拔协议。 |
| `contracts/` | v4 Layer 1：稀疏契约矩阵 + 解析器（`ContractViolation`、`ContractResolver`；内置 + 学习到的违规） |
| `validator/` | v4 Layer 2：`FastValidator`——单列/跨列校验器、复合 FK、shadow-FK 扫描、方言解析器、schema 快照 |
| `repair/` | v4 Layer 3：无状态修复引擎（`REPAIR_STRATEGIES` 纯函数、`executor.py`、`pipeline.py`） |
| `healer/` | v4 Layer 4：4 级 LLM 修复架构，按失败类型路由（subgraph → column → compact → degrade） |
| `auto_heal/` | v4 Layer 5：`AutoHealOrchestrator` 顶层入口（ai-analyze 默认路径、`auto-heal` 命令）+ `TimeBudgetController` |
| `refiner.py` | 自我纠错循环（normal → compact → ultra-compact） |
| `ai_mediator.py` | AI 专属中介（`apply_ai_suggestions()` hook 实现、`AI_APPLICABLE_GENERATORS`） |
| `config.py` | `AIConfig` 模型。`backend: AIBackend` 枚举（值：`google_ai_studio`、`lm_studio`、`ollama`、`openai_compat`；**无 `gemma4` backend**）。`tool_calling_protocol: Literal["gemma4", "openai", "none"]` 字段（Phase E）选择原生函数调用协议；`resolve_tool_calling_protocol()` 按后端支持收窄。 |
| `_hardware.py` | 跨平台 RAM/GPU 检测 + Gemma 模型硬件需求 |
| `cli/ai_commands.py` | 3 个 AI CLI 命令（`ai-suggest`、`ai-analyze`、`auto-heal`），通过 `register()` entry point 注入 |
| `mcp.py`（可选） | AI MCP 服务器——4 个工具（`sqlseed_ai_generate_yaml`、`sqlseed_gemma4_analyze`、`sqlseed_gemma4_agent_fill`、`sqlseed_list_gemma_models`）；`pip install sqlseed-ai[mcp]` |
| Entry point | CLI：3 个命令（`ai-suggest`、`ai-analyze`、`auto-heal`）通过 entry_points 注入 `sqlseed` CLI |

**安装**：`pip install sqlseed-ai`（完全独立的包）

**Gemma4 作为长期 LLM 后端**（2026-06-26 修订）：
- Gemma4 **不是**比赛专用代码。它是长期支持的 LLM 后端（Apache 2.0，无 MAU 限制，支持在线 + 离线）。
- 无 `sqlseed_ai/gemma4/` 子目录（避免暗示可移除性）。
- Gemma4 原生函数调用位于 `analyzer/_tool_calling.py`，作为**协议实现**（`tool_calling_protocol="gemma4"`），与 `"openai"` 和 `"none"` 并列。
- Gemma4 通过标准后端访问：`backend="ollama"` + `model="gemma4:26b"`，或 `backend="google_ai_studio"` + `model="gemma-4-..."`。
- **Gemma5 过渡**：如果 Gemma5 保持相同的 6 个特殊 token（`<|tool>`, `<|tool_call>` 等），零代码改动。如果 Gemma5 改变了 token，添加 `tool_calling_protocol="gemma5"`——无需移除 `"gemma4"`（向后兼容）。

### 3.4 插件：`mcp-server-sqlseed`（`plugins/mcp-server-sqlseed/`）

| 组件 | 职责 |
|------|------|
| 工具 | `sqlseed_generate_yaml`（从 schema 生成模板，**规则驱动，无 LLM**）, `sqlseed_execute_fill` |
| 不包含 | ~~`sqlseed_inspect_schema`~~（使用 mcp-database-server / mcp-db-analyzer） |
| 不包含 | ~~`sqlseed_gemma4_analyze`~~ / ~~`sqlseed_gemma4_agent_fill`~~ / ~~`sqlseed_list_gemma_models`~~（在 sqlseed-ai[mcp] 中） |
| 不包含 | ~~`sqlseed://schema` Resource~~（schema 检查由其他 MCP 负责） |

**安装**：`pip install mcp-server-sqlseed`

**设计原则**：mcp-server-sqlseed 通过 MCP 暴露**核心能力**（基于规则的 YAML 模板生成 + 执行填充）。它**不依赖**任何 LLM。无论是作为本地 stdio MCP 服务器（离线）部署，还是作为远程 HTTP MCP 服务器（在线）部署，其功能完全相同，不会因网络问题失败。

**YAML 生成是核心能力**（2026-06-26 修订）：
- `sqlseed_generate_yaml` 调用核心 `ColumnMapper`（75 条精确规则 + 29 个模式）——规则驱动、离线、确定性。
- `sqlseed-ai[mcp]` 提供 `sqlseed_ai_generate_yaml`——LLM 驱动，需要 LLM 运行时。
- **边界**：两个 MCP 的分界线是"是否需要 LLM 运行时"，**不是**"在线/离线"。
- **交集定义**（两者都生成 YAML）：
  - mcp-server-sqlseed：规则驱动（核心 mapper），适合简单 schema，离线可用。
  - sqlseed-ai[mcp]：LLM 驱动（AI 分析器），适合需要语义推断的复杂 schema。
- Schema 检查由现有的成熟 MCP 处理：
  - [@adevguide/mcp-database-server](https://github.com/iPraBhu/mcp-database-server) — SQLite/PostgreSQL/MySQL schema 发现
  - [mcp-db-analyzer](https://github.com/Dmitriusan/mcp-db-analyzer) — SQLite/PostgreSQL/MySQL `inspect_schema`

---

## 4. 依赖方向

```
用户代码
    │
    ▼
sqlseed（核心）◄──── plugins/sqlseed-cli (CLI)
    │                plugins/sqlseed-ai (AI)
    │                plugins/mcp-server-sqlseed (MCP)
    │
    ▼
sqlseed._utils（无内部依赖，被所有层使用）
```

**严格规则**（由 `lint-imports` 强制执行）：
- `generators/` → 永不导入 `core/`
- `database/` → 永不导入 `core/`
- `_utils/` → 永不导入任何上层
- 插件 → 导入 `sqlseed` 核心，永不互相导入（除 sqlseed-ai 可为 CLI entry point 导入 sqlseed-cli）

---

## 5. 数据库支持

| 数据库 | 状态 | 适配器 |
|--------|------|--------|
| SQLite | ✅ 默认（内置） | `SQLAlchemyAdapter` |
| PostgreSQL | ✅ 已实现（扩展） | `SQLAlchemyAdapter` + `psycopg` |
| MySQL | ❌ 已移除（推迟到 PostgreSQL 完全验证后再接入） | — |

**安装**：`pip install sqlseed[postgres]` 以支持 PostgreSQL。

---

## 6. 安装矩阵

| 使用场景 | 安装命令 | 获得的功能 |
|---------|---------|-----------|
| 仅 Python API（离线） | `pip install sqlseed` | `from sqlseed import fill` |
| + CLI | `pip install sqlseed-cli` | `sqlseed` 命令 |
| + AI YAML 生成 | `pip install sqlseed-ai` | `sqlseed ai-suggest` + Gemma4 支持 |
| + PostgreSQL | `pip install sqlseed[postgres]` | PostgreSQL 支持 |
| + mimesis（高性能） | `pip install sqlseed[mimesis]` | MimesisProvider |
| + MCP 服务器（核心能力） | `pip install mcp-server-sqlseed` | 基于规则的 YAML + 填充的 MCP 工具 |
| + AI MCP | `pip install sqlseed-ai[mcp]` | LLM 驱动 YAML 的 AI MCP 工具 |
| 全部功能 | 安装以上所有 | 所有可选功能 |

> [!NOTE]
> **依赖链**：`sqlseed-ai` 依赖 `sqlseed-cli`（`ai-suggest` 命令通过 `entry_points` 注入 `sqlseed` CLI）。安装 `sqlseed-ai` 会自动拉取 `sqlseed-cli` 作为依赖。仅安装 `sqlseed-ai` 而不安装 `sqlseed-cli` **不是**受支持的配置。

### 6.1 版本兼容性策略

4 个独立包（`sqlseed`、`sqlseed-cli`、`sqlseed-ai`、`mcp-server-sqlseed`）各有独立版本号，以下策略管理跨包兼容性：

| 变更类型 | 版本影响 | 插件操作 |
|---------|---------|---------|
| 核心新增 pluggy hookspec（向后兼容） | 小版本提升 | 插件可选实现新 hook；无需强制更新 |
| 核心移除/修改 hookspec 签名（破坏性） | 大版本提升 | 插件必须 pin `sqlseed>=CURRENT_MAJOR,<NEXT_MAJOR` 并更新 |
| 核心内部重构（无 hookspec 变更） | 补丁/小版本提升 | 插件不受影响 |

**插件 pin 规则**：每个插件的 `pyproject.toml` 必须声明 `dependencies = ["sqlseed>=X.Y,<X.(Y+1)"]`（或 `<(X+1).0` 以获得大版本稳定性）。示例：`mcp-server-sqlseed` 已实践此规则（`sqlseed>=0.1.0,<2`）。

---

## 7. 对齐决策记录

### 7.1 CLI 作为插件（不在核心中）

**决策**：CLI 代码移至 `plugins/sqlseed-cli/`。核心包无 `[project.scripts]`。

**理由**：
- sqlseed 的核心是 Python API（类似 sqlalchemy/pandas），不是 CLI 工具（不像 pytest/black）
- 核心不能依赖 click/rich 以保持长期稳定
- 只使用 Python API 的用户不需要 CLI 依赖
- `pip install sqlseed-cli` 提供 `sqlseed` 命令

**用户原话**："cli、ai、MCP是可选功能，在用户不安装时，核心逻辑不用强制保留"

### 7.2 AI 代码在插件中（不在核心中）

**决策**：所有 AI 相关代码移至 `plugins/sqlseed-ai/`。核心无 AI 逻辑。

**理由**：
- AI 需要网络/API 访问，违反离线优先原则
- 核心必须保持稳定，不受 AI 技术变化影响
- `core/enrichment.py` **整体**保留在核心（`EnrichmentEngine` 是本地计算，无 AI 逻辑）
- `core/plugin_mediator.py` 仅保留通用方法（`apply_batch_transforms`, `apply_template_pool`）；AI 专用 `apply_ai_suggestions()` 移出

**用户原话**："核心功能要保证离线也可以正常使用，所以sqlseed-ai、sqlseed-cli都需要是插件形式"

### 7.3 MySQL 移除

**决策**：删除所有 MySQL 相关代码。

**理由**：
- 用户确认仅实现了 SQLite + PostgreSQL
- MySQL 推迟到 PostgreSQL 完全验证后再接入
- 保留未测试的 MySQL 代码违反代码整洁原则

**用户原话**："MySql暂时不添加，保证代码的整洁性，等postgresql完全调通后再去接入会更好，所以相关的内容需要删除"

### 7.4 Gemma4 作为长期 LLM 后端

**决策**：Gemma4 是 sqlseed-ai 中长期支持的 LLM 后端，**不是**比赛专用代码。无隔离的 `gemma4/` 子目录。

**理由**：
- Gemma4 是 Apache 2.0，无 MAU 限制——法律和商业上可长期使用
- Gemma4 支持在线（Google AI Studio）和离线（Ollama/LM Studio）部署
- 原生函数调用实现为可插拔的 `tool_calling_protocol`（与 `"openai"` 和 `"none"` 并列），不是 Gemma4 专用代码
- Gemma4 通过标准后端访问（`backend="ollama"` + `model="gemma4:26b"`），无 `backend="gemma4"` 配置
- Gemma5 过渡：如果协议不变，零代码改动；如果改变，添加新协议选项（向后兼容）
- 避免浪费比赛期间的工程投入到一次性代码上

**用户原话**："相关gemma4问题取决于是否想要长期保留" → 用户确认长期保留。
**用户原话**："不能因为比赛所涉及到的代码而污染整个项目，因为比赛只是短期内的，比赛过后要保证代码可以长期使用" → 通过将 Gemma4 视为标准后端而非比赛代码来解决。

### 7.5 MCP 范围与边界

**决策**：两个 MCP，以"是否需要 LLM 运行时"为明确边界：
- `mcp-server-sqlseed`：`sqlseed_generate_yaml`（规则驱动，无 LLM）+ `sqlseed_execute_fill`。暴露**核心能力**。
- `sqlseed-ai[mcp]`：`sqlseed_ai_generate_yaml`（LLM 驱动）。暴露**AI 插件能力**。

**理由**：
- YAML 模板生成是**核心能力**（使用 `ColumnMapper` 的 75 条精确规则 + 29 个模式），不是 AI 功能
- AI YAML 生成是对需要语义推断的复杂 schema 的**增强**
- 分界线是"是否需要 LLM 运行时"，**不是**"在线/离线"（MCP 协议对部署模式中立）
- **交集定义**（两者都生成 YAML）：mcp-server-sqlseed = 规则驱动（离线可用、确定性）；sqlseed-ai[mcp] = LLM 驱动（需要 LLM 运行时、语义推断）
- 多个成熟 MCP 已提供多数据库 schema 检查，因此移除 inspect_schema

**用户原话**："yml生成是不是核心逻辑？ai和mcp只是辅助手段" → 确认：YAML 模板生成是核心，AI 是辅助。
**用户原话**："纯离线用 mcp-server-sqlseed这句话描述的是不是不准确...MCP应该是在线离线都支持吧" → 修正：边界是 LLM 依赖，不是在线/离线。

### 7.6 插件系统保留在核心中

**决策**：`src/sqlseed/plugins/`（hookspecs + 管理器）保留在核心包。仅 AI 专用中介移出。

**理由**：
- pluggy 轻量，不影响核心稳定性
- 插件系统是"外部插件接入核心"的基础设施
- 没有它，sqlseed-ai/sqlseed-cli 无法集成

**用户原话**："外部以插件形式接入核心功能来完成数据库的测试数据生成"

---

## 8. 重构清单

将代码与本文档对齐的工作项（在独立分支中执行）：

### Phase A：MySQL 移除
- [ ] 清理 `database/_dialect.py` 中的 MySQL 提及（仅注释/文档字符串，无 `MySQLDialect` 类）
- [ ] 删除 `database/_type_normalizer.py` 中的 `_MYSQL_TYPE_MAP` + `dialect_name == "mysql"` 分支
- [ ] 删除 `database/sqlalchemy_adapter.py` 中的 `if "mysql" in db_url` + `if dialect_name == "mysql"` 分支
- [ ] 删除 `pyproject.toml` 中的 `mysql` 可选依赖
- [ ] 删除测试和文档中的 MySQL 引用

### Phase B：CLI 提取
- [ ] 创建 `plugins/sqlseed-cli/` 包，拥有独立 `pyproject.toml`
- [ ] 移动 `src/sqlseed/cli/` → `plugins/sqlseed-cli/src/sqlseed_cli/`
- [ ] 移动 `ai_commands.py` → `plugins/sqlseed-ai/src/sqlseed_ai/cli/`
- [ ] 从核心 `pyproject.toml` 移除 `[project.scripts]`
- [ ] 添加 `cli` 可选依赖指向 `sqlseed-cli`
- [ ] 移动 CLI 测试到 `plugins/sqlseed-cli/tests/`

### Phase C：AI 代码提取
- [ ] `core/enrichment.py` **整体**保留在核心（`EnrichmentEngine` 是本地计算，无 AI 逻辑需移出）
- [ ] 移动 `core/plugin_mediator.py` 的 `apply_ai_suggestions()` → `plugins/sqlseed-ai/`
- [ ] 保留 `apply_batch_transforms()` + `apply_template_pool()` 在核心 `plugin_mediator.py`
- [ ] Orchestrator 通过 pluggy hook 调用 AI（`plugins.hook.sqlseed_ai_analyze_table()`）

### Phase D：MCP 范围收窄
- [ ] 从 mcp-server-sqlseed 移除 `sqlseed_inspect_schema` 工具
- [ ] 移除 `sqlseed_gemma4_analyze`, `sqlseed_gemma4_agent_fill`, `sqlseed_list_gemma_models` 工具
- [ ] 移除 `sqlseed://schema` Resource
- [ ] 仅保留 `sqlseed_generate_yaml`（规则驱动）+ `sqlseed_execute_fill`
- [ ] 将 AI MCP 工具移至 `sqlseed-ai[mcp]`

### Phase E：Gemma4 协议抽象
- [ ] 确保 Gemma4 原生函数调用在 `analyzer/_tool_calling.py` 中作为协议实现
- [ ] 确保 `AIConfig.backend` 使用标准后端（无 `gemma4`）
- [ ] 确保 `AIConfig.tool_calling_protocol: Literal["gemma4", "openai", "none"]`
- [ ] 无 `gemma4/` 子目录
- [ ] 无需赛后清理（Gemma4 是长期后端）

### Phase F：测试重组
- [ ] 核心测试保留在 `tests/`
- [ ] 创建 `plugins/sqlseed-cli/tests/`
- [ ] 移动 AI 测试到 `plugins/sqlseed-ai/tests/`
- [ ] 移动 MCP 测试到 `plugins/mcp-server-sqlseed/tests/`
- [ ] 更新 CI 按包运行测试

### Phase G：文档同步（最终步骤）
- [ ] 用所有对齐决策更新 `CLAUDE.md`
- [ ] 用对应章节更新 `AGENTS.md`
- [ ] `GEMINI.md` 保持指向 `CLAUDE.md` 的指针
- [ ] 运行 `pytest tests/test_doc_sync.py` 验证一致性

---

## 9. 防御机制（防腐化）

四层互补机制防止核心代码腐化和 mock 自证陷阱：

| 层 | 工具 | 防止什么 |
|---|------|---------|
| (a) 架构契约 | `lint-imports`（3 个契约） | 跨层依赖违规 |
| (b) 架构守护测试 | `tests/test_architecture.py`（13 个测试） | 模块边界/数量契约漂移 |
| (c) 变异测试 | `make mutmut` | 自证 mock 测试（量化基线） |
| (d) 文档同步 | `tests/test_doc_sync.py` | 文档与代码数量不匹配 |

**合并前 4 层必须全部通过。** 详情见 `CLAUDE.md` Critical Pitfalls #13-#14。

---

## 10. Gemma4 长期维护（无需赛后清理）

Gemma4 是**长期 LLM 后端**，**不是**比赛专用代码。**没有赛后清理**。

### Gemma5 过渡流程

当 Gemma5 发布时，按以下步骤操作：

1. 检查 Gemma5 是否使用相同的 6 个特殊 token（`<|tool>`, `<|tool_call>`, `<|tool_result>` 等）
2. **如果 token 相同**：零代码改动。用户只需更新模型名：`model="gemma5:xx"`
3. **如果 token 不同**：在 `AIConfig.tool_calling_protocol` Literal 选项中添加 `tool_calling_protocol="gemma5"`，在 `analyzer/_tool_calling.py` 中实现新协议
4. 不要从协议选项中移除 `"gemma4"`（向后兼容）
5. 更新 `_model_selector.py` 以包含 Gemma5 模型条目
6. 运行完整测试套件 + `lint-imports` + `make mutmut` 验证无破坏
7. 更新 `CLAUDE.md` / `AGENTS.md` 添加 Gemma5 引用

**关键**：Gemma4 支持无限期保留。通用 AI 功能（analyzer/, refiner.py）继续在所有后端上工作。
