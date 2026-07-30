# sqlseed Project Architecture Decisions

**Created:** 2026-06-26
**Status:** Aligned with user requirements (Round 6 revisions applied)
**Purpose:** Authoritative architecture reference for AI agents (CLAUDE/AGENTS/GEMINI) and contributors. All code changes must conform to this document.

---

## 1. Project Vision

sqlseed is a **declarative multi-database test data generation toolkit**. It focuses exclusively on writing reasonable test data to databases — no other functionality.

### Core Principles

1. **Core stability**: The core package (`sqlseed`) must remain stable and not be impacted by AI or external technology shifts. External features evolve as plugins.
2. **Offline-first**: Core functionality must work offline without external network dependencies. AI/CLI/MCP features are optional plugins.
3. **Python API first**: The core is a Python library (`from sqlseed import fill`). CLI is a convenience layer, not the core.
4. **Plugin architecture**: External features (CLI, AI, MCP) connect to the core via plugins. Users install only what they need.

### Target Users

- Test engineers (use CLI: `sqlseed fill app.db -t users -n 1000`)
- Database developers (use Python API: `from sqlseed import fill`)
- Data specialists (use Python API for data pipelines)

---

## 2. Architecture Overview

```
                    ┌─────────────────────────────────────────┐
                    │           User Install Choices           │
                    │  pip install sqlseed              (core) │
                    │  pip install sqlseed-cli           (CLI) │
                    │  pip install sqlseed-ai             (AI) │
                    │  pip install mcp-server-sqlseed    (MCP) │
                    └────────────────────┬────────────────────┘
                                         │
                    ┌────────────────────▼────────────────────┐
                    │           sqlseed (Core Package)         │
                    │  ┌────────────────────────────────────┐ │
                    │  │ Python API: fill, connect, preview │ │
                    │  │ fill_from_config, load_config      │ │
                    │  └────────────────────────────────────┘ │
                    │  ┌──────────┐ ┌──────────┐ ┌──────────┐ │
                    │  │ core/    │ │generators│ │ database/│ │
                    │  │(logic)   │ │(data)    │ │ (adapters)│ │
                    │  └──────────┘ └──────────┘ └──────────┘ │
                    │  ┌──────────┐ ┌──────────┐               │
                    │  │ plugins/ │ │ config/  │               │
                    │  │(hookspecs│ │(models,  │               │
                    │  │+manager) │ │ loader)  │               │
                    │  └──────────┘ └──────────┘               │
                    │  ┌──────────────────────────────────┐   │
                    │  │ _utils/ (no internal deps)       │   │
                    │  └──────────────────────────────────┘   │
                    └────────────────────┬────────────────────┘
                                         │ pluggy hooks
                    ┌────────────────────▼────────────────────┐
                    │              Plugin Layer                 │
                    │                                          │
                    │  ┌─────────────┐  ┌──────────────────┐  │
                    │  │ sqlseed-cli │  │   sqlseed-ai     │  │
                    │  │ (CLI: fill, │  │ (AI YAML gen,    │  │
                    │  │  preview,   │  │  Gemma4 as       │  │
                    │  │  inspect,   │  │  long-term LLM   │  │
                    │  │  init,      │  │  backend via     │  │
                    │  │  replay)    │  │  tool_calling_   │  │
                    │  │             │  │  protocol,       │  │
                    │  │             │  │  self-correction)│  │
                    │  │             │  │  + optional MCP  │  │
                    │  │             │  │    interface     │  │
                    │  └─────────────┘  └──────────────────┘  │
                    │                                          │
                    │  ┌────────────────────────────────────┐ │
                    │  │ mcp-server-sqlseed                 │ │
                    │  │ (MCP: generate_yaml [rule-driven,  │ │
                    │  │  no LLM], execute_fill — core      │ │
                    │  │  capabilities ONLY, no schema      │ │
                    │  │  inspection, no AI)                │ │
                    │  └────────────────────────────────────┘ │
                    └──────────────────────────────────────────┘
```

---

## 3. Module Responsibilities

> [!IMPORTANT]
> The following describes the **target architecture** after refactoring (Phase A-G).
> Current code differs — see Section 8 "Refactoring Checklist" for the gap and execution steps.
> Method/function names shown here are the **target names**; where current code differs, the
> current name is noted in parentheses.

### 3.1 Core Package (`src/sqlseed/`)

**Stays in core** (offline, stable, no CLI/AI dependencies):

| Module | Responsibility | Key Classes/Functions |
|--------|---------------|----------------------|
| `__init__.py` | Public Python API | `fill`, `connect`, `preview`, `fill_from_config`, `load_config` |
| `core/orchestrator/` | Central coordinator (4 mixins + shared data) | `DataOrchestrator` |
| `core/mapper.py` | 9-level column mapping strategy chain | `ColumnMapper`, `GeneratorSpec` |
| `core/schema.py` | Schema inference from database | `SchemaInferrer` |
| `core/relation.py` | FK integrity + cross-table relations | `RelationResolver`, `SharedPool` |
| `core/column_dag.py` | Topological sort for `derive_from` deps | `ColumnDAG` |
| `core/expression.py` | `derive_from` expression engine (simpleeval) | `ExpressionEngine` |
| `core/constraints.py` | UNIQUE enforcement with backtracking | `ConstraintSolver` |
| `core/transform.py` | Row/batch transform pipeline | `load_transform()` |
| `core/result.py` | Generation result dataclass | `GenerationResult` |
| `core/stream.py` | DataStream batch generation iterator | `DataStream` |
| `core/unique_adjuster.py` | Post-generation UNIQUE adjustment | `UniqueAdjuster` |
| `core/plugin_mediator.py` | **Generic** plugin mediation only (target: AI-specific `apply_ai_suggestions()` moved out) | `apply_batch_transforms()`, `apply_template_pool()` |
| `core/enrichment.py` | Enum detection + local enrichment (no AI logic, stays **entirely** in core) | `EnrichmentEngine` (current: `is_enumeration_column()`, `apply()`) |
| `generators/` | Data providers (faker required, mimesis optional) | `FakerProvider`, `MimesisProvider`, `BaseProvider` |
| `database/` | DB adapters: SQLAlchemy (required, SQLite+PostgreSQL) | `SQLAlchemyAdapter`, `RawSQLiteAdapter` (test-only) |
| `plugins/` | pluggy hookspecs + manager (plugin infrastructure) | `PluginManager`, hookspecs |
| `config/` | Pydantic models, YAML loader, SnapshotManager | `GeneratorConfig`, `SnapshotManager` |
| `_utils/` | Internal utilities (no internal deps) | `sql_safe`, `logger`, `metrics`, `progress`, `paths` |

**Moves OUT of core** (to plugins):

| Current Location | Destination | Reason |
|-----------------|-------------|--------|
| `cli/` (entire directory) | `plugins/sqlseed-cli/` | CLI is optional, depends on click/rich |
| `cli/ai_commands.py` | `plugins/sqlseed-ai/` | AI CLI command, needs network |
| `core/plugin_mediator.py` `apply_ai_suggestions()` | `plugins/sqlseed-ai/` | AI-specific mediation |

**Deleted** (MySQL support):

| Location | Action |
|----------|--------|
| `database/_dialect.py` MySQL mentions (comments/docstrings only, **no `MySQLDialect` class exists**) | Clean |
| `database/_type_normalizer.py` `_MYSQL_TYPE_MAP` + `dialect_name == "mysql"` branch | Delete |
| `database/sqlalchemy_adapter.py` `if "mysql" in db_url` + `if dialect_name == "mysql"` branches | Delete |
| `pyproject.toml` `mysql` optional dep | Delete |
| Tests/docs referencing MySQL | Delete |

### 3.2 Plugin: `sqlseed-cli` (`plugins/sqlseed-cli/`)

| Component | Responsibility |
|-----------|---------------|
| `cli/main.py` | Commands: `fill`, `preview`, `inspect`, `init`, `replay` |
| `cli/_utils.py` | `sanitize_table_config()` for LLM config cleaning |
| Entry point | `[project.scripts] sqlseed = sqlseed_cli:main` |
| Dependencies | `sqlseed` (core), `click`, `rich` |

**Install**: `pip install sqlseed-cli` (completely independent package with own `pyproject.toml`, independent version, independent release)

### 3.3 Plugin: `sqlseed-ai` (`plugins/sqlseed-ai/`)

| Component | Responsibility |
|-----------|---------------|
| `analyzer/` | LLM table-level analysis (streaming, tool-calling). Contains `_tool_calling.py` with pluggable protocol implementations. |
| `contracts/` | v4 Layer 1: sparse contract matrix + resolver (`ContractViolation`, `ContractResolver`; builtin + learned violations) |
| `validator/` | v4 Layer 2: `FastValidator` — single/cross-column validators, composite FK, shadow-FK scan, dialect parser, schema snapshot |
| `repair/` | v4 Layer 3: stateless repair engine (`REPAIR_STRATEGIES` pure functions, `executor.py`, `pipeline.py`) |
| `healer/` | v4 Layer 4: 4-level LLM heal architecture with failure-type-aware routing (subgraph → column → compact → degrade) |
| `auto_heal/` | v4 Layer 5: `AutoHealOrchestrator` top-level entry (ai-analyze default path, `auto-heal` command) + `TimeBudgetController` |
| `refiner.py` | Self-correction loop (normal → compact → ultra-compact) |
| `ai_mediator.py` | AI-specific mediation (`apply_ai_suggestions()` hook impl, `AI_APPLICABLE_GENERATORS`) |
| `config.py` | `AIConfig` model. `backend: AIBackend` enum (values: `google_ai_studio`, `lm_studio`, `ollama`, `openai_compat`; **NO `gemma4` backend**). `tool_calling_protocol: Literal["gemma4", "openai", "none"]` field (Phase E) selects the native function calling protocol; `resolve_tool_calling_protocol()` narrows based on backend support. |
| `_hardware.py` | Cross-platform RAM/GPU detection + Gemma model hardware requirements |
| `cli/ai_commands.py` | 3 AI CLI commands (`ai-suggest`, `ai-analyze`, `auto-heal`), injected via `register()` entry point |
| `mcp.py` (optional) | AI MCP server — 4 tools (`sqlseed_ai_generate_yaml`, `sqlseed_gemma4_analyze`, `sqlseed_gemma4_agent_fill`, `sqlseed_list_gemma_models`); `pip install sqlseed-ai[mcp]` |
| Entry point | CLI: 3 commands injected into `sqlseed` CLI via entry_points: `ai-suggest` (per-table LLM analysis), `ai-analyze` (default v4 AutoHealOrchestrator path), `auto-heal` (standalone YAML repair) |

**Install**: `pip install sqlseed-ai` (completely independent package)

**Gemma4 as long-term LLM backend** (revised 2026-06-26):
- Gemma4 is **NOT** competition-only code. It is a long-term supported LLM backend (Apache 2.0, no MAU limits, online + offline capable).
- No `sqlseed_ai/gemma4/` subdirectory (avoids implying removability).
- Gemma4 native function calling lives in `analyzer/_tool_calling.py` as a **protocol implementation** (`tool_calling_protocol="gemma4"`), alongside `"openai"` and `"none"`.
- Gemma4 accessed via standard backends: `backend="ollama"` + `model="gemma4:26b"`, or `backend="google_ai_studio"` + `model="gemma-4-..."`.
- **Gemma5 transition**: If Gemma5 keeps the same 6 special tokens (`<|tool>`, `<|tool_call>`, etc.), zero code change. If Gemma5 changes tokens, add `tool_calling_protocol="gemma5"` — no removal of `"gemma4"` needed (backward compatible).

### 3.4 Plugin: `mcp-server-sqlseed` (`plugins/mcp-server-sqlseed/`)

| Component | Responsibility |
|-----------|---------------|
| Tools | `sqlseed_generate_yaml` (template from schema, **rule-driven, no LLM**), `sqlseed_execute_fill` |
| NOT included | ~~`sqlseed_inspect_schema`~~ (use mcp-database-server / mcp-db-analyzer) |
| NOT included | ~~`sqlseed_gemma4_analyze`~~ / ~~`sqlseed_gemma4_agent_fill`~~ / ~~`sqlseed_list_gemma_models`~~ (in sqlseed-ai[mcp]) |
| NOT included | ~~`sqlseed://schema` Resource~~ (schema inspection by other MCPs) |

**Install**: `pip install mcp-server-sqlseed`

**Design principle**: mcp-server-sqlseed exposes **core capabilities** (rule-based YAML template generation + execute fill) via MCP. It does **NOT** depend on any LLM. Whether deployed as local stdio MCP server (offline) or remote HTTP MCP server (online), its functionality is identical and never fails due to network issues.

**YAML generation is a core capability** (revised 2026-06-26):
- `sqlseed_generate_yaml` calls core `ColumnMapper` (75 exact rules + 29 patterns) — rule-driven, offline, deterministic.
- `sqlseed-ai[mcp]` provides `sqlseed_ai_generate_yaml` — LLM-driven, requires LLM runtime.
- **Boundary**: The dividing line between the two MCPs is "whether LLM runtime is required", NOT "online/offline".
- **Intersection definition** (both generate YAML):
  - mcp-server-sqlseed: rule-driven (core mapper), good for simple schemas, offline-capable.
  - sqlseed-ai[mcp]: LLM-driven (AI analyzer), good for complex schemas requiring semantic inference.
- Schema inspection is handled by existing mature MCPs:
  - [@adevguide/mcp-database-server](https://github.com/iPraBhu/mcp-database-server) — SQLite/PostgreSQL/MySQL schema discovery
  - [mcp-db-analyzer](https://github.com/Dmitriusan/mcp-db-analyzer) — SQLite/PostgreSQL/MySQL `inspect_schema`

---

## 4. Dependency Direction

```
User code
    │
    ▼
sqlseed (core) ◄──── plugins/sqlseed-cli (CLI)
    │                plugins/sqlseed-ai (AI)
    │                plugins/mcp-server-sqlseed (MCP)
    │
    ▼
sqlseed._utils (no internal deps, used by all)
```

**Strict rules** (enforced by `lint-imports`):
- `generators/` → never imports `core/`
- `database/` → never imports `core/`
- `_utils/` → never imports any upper layer
- Plugins → import `sqlseed` core, never each other (except sqlseed-ai may import sqlseed-cli for CLI entry point)

---

## 5. Database Support

| Database | Status | Adapter |
|----------|--------|---------|
| SQLite | ✅ Default (built-in) | `SQLAlchemyAdapter` |
| PostgreSQL | ✅ Implemented (extension) | `SQLAlchemyAdapter` + `psycopg` |
| MySQL | ❌ Removed (deferred until PostgreSQL fully validated) | — |

**Install**: `pip install sqlseed[postgres]` for PostgreSQL support.

---

## 6. Installation Matrix

| Use Case | Install Command | What You Get |
|----------|----------------|--------------|
| Python API only (offline) | `pip install sqlseed` | `from sqlseed import fill` |
| + CLI | `pip install sqlseed-cli` | `sqlseed` command |
| + AI YAML generation | `pip install sqlseed-ai` | `sqlseed ai-suggest` / `ai-analyze` / `auto-heal` + Gemma4 support |
| + PostgreSQL | `pip install sqlseed[postgres]` | PostgreSQL support |
| + mimesis (high-perf) | `pip install sqlseed[mimesis]` | MimesisProvider |
| + MCP server (core capabilities) | `pip install mcp-server-sqlseed` | MCP tools for rule-based YAML + fill |
| + AI MCP | `pip install sqlseed-ai[mcp]` | AI MCP tools for LLM-driven YAML |
| Everything | Install all above | All optional features |

> [!NOTE]
> **Dependency chain**: `sqlseed-ai` depends on `sqlseed-cli` (3 AI commands — `ai-suggest`, `ai-analyze`, `auto-heal` — are injected into the `sqlseed` CLI via `entry_points`). Installing `sqlseed-ai` will auto-pull `sqlseed-cli` as a dependency. Installing `sqlseed-ai` without `sqlseed-cli` is **not** a supported configuration.

### 6.1 Version Compatibility Policy

With 4 independent packages (`sqlseed`, `sqlseed-cli`, `sqlseed-ai`, `mcp-server-sqlseed`), each with independent versioning, the following policy governs cross-package compatibility:

| Change Type | Version Impact | Plugin Action |
|-------------|----------------|---------------|
| Core adds new pluggy hookspec (backward compatible) | Minor bump | Plugins optionally implement new hook; no forced update |
| Core removes/changes hookspec signature (breaking) | Major bump | Plugins MUST pin `sqlseed>=CURRENT_MAJOR,<NEXT_MAJOR` and update |
| Core internal refactor (no hookspec change) | Patch/Minor bump | Plugins unaffected |

**Plugin pinning rule**: Each plugin's `pyproject.toml` MUST declare `dependencies = ["sqlseed>=X.Y,<X.(Y+1)"]` (or `<(X+1).0` for major stability). Example: `mcp-server-sqlseed` already practices this (`sqlseed>=0.1.0,<2`).

---

## 7. Alignment Decision Record

### 7.1 CLI as Plugin (not in core)

**Decision**: CLI code moves to `plugins/sqlseed-cli/`. Core package has no `[project.scripts]`.

**Rationale**:
- sqlseed's core is a Python API (like sqlalchemy/pandas), not a CLI tool (unlike pytest/black)
- Core must not depend on click/rich for long-term stability
- Users who only use Python API don't need CLI dependencies
- `pip install sqlseed-cli` provides the `sqlseed` command

**User quote**: "cli、ai、MCP是可选功能，在用户不安装时，核心逻辑不用强制保留"

### 7.2 AI Code in Plugin (not in core)

**Decision**: All AI-related code moves to `plugins/sqlseed-ai/`. Core has zero AI logic.

**Rationale**:
- AI requires network/API access, violating offline-first principle
- Core must remain stable regardless of AI technology shifts
- `core/enrichment.py` stays **entirely** in core (`EnrichmentEngine` is local computation, no AI logic)
- `core/plugin_mediator.py` keeps only generic methods (`apply_batch_transforms`, `apply_template_pool`); AI-specific `apply_ai_suggestions()` moves out

**User quote**: "核心功能要保证离线也可以正常使用，所以sqlseed-ai、sqlseed-cli都需要是插件形式"

### 7.3 MySQL Removed

**Decision**: Delete all MySQL-related code.

**Rationale**:
- User confirmed only SQLite + PostgreSQL are implemented
- MySQL deferred until PostgreSQL fully validated
- Keeping untested MySQL code violates code cleanliness principle

**User quote**: "MySql暂时不添加，保证代码的整洁性，等postgresql完全调通后再去接入会更好，所以相关的内容需要删除"

### 7.4 Gemma4 as Long-term LLM Backend

**Decision**: Gemma4 is a long-term supported LLM backend in sqlseed-ai, NOT competition-only code. No isolated `gemma4/` subdirectory.

**Rationale**:
- Gemma4 is Apache 2.0, no MAU limits — legally and commercially viable long-term
- Gemma4 supports both online (Google AI Studio) and offline (Ollama/LM Studio) deployment
- Native function calling is implemented as a pluggable `tool_calling_protocol` (alongside `"openai"` and `"none"`), not as Gemma4-specific code
- Gemma4 accessed via standard backends (`backend="ollama"` + `model="gemma4:26b"`), no `backend="gemma4"` config
- Gemma5 transition: if protocol unchanged, zero code change; if changed, add new protocol option (backward compatible)
- Avoids wasting competition-period engineering effort on throwaway code

**User quote**: "相关gemma4问题取决于是否想要长期保留" → User confirmed long-term retention.
**User quote**: "不能因为比赛所涉及到的代码而污染整个项目，因为比赛只是短期内的，比赛过后要保证代码可以长期使用" → Resolved by treating Gemma4 as a standard backend, not competition code.

### 7.5 MCP Scope and Boundary

**Decision**: Two MCPs with clear boundary based on "whether LLM runtime is required":
- `mcp-server-sqlseed`: `sqlseed_generate_yaml` (rule-driven, no LLM) + `sqlseed_execute_fill`. Exposes **core capabilities**.
- `sqlseed-ai[mcp]`: `sqlseed_ai_generate_yaml` (LLM-driven). Exposes **AI plugin capabilities**.

**Rationale**:
- YAML template generation is a **core capability** (uses `ColumnMapper` with 75 exact rules + 29 patterns), not an AI feature
- AI YAML generation is an **enhancement** for complex schemas requiring semantic inference
- The dividing line is "whether LLM runtime is required", NOT "online/offline" (MCP protocol is neutral to deployment mode)
- **Intersection definition** (both generate YAML): mcp-server-sqlseed = rule-driven (offline-capable, deterministic); sqlseed-ai[mcp] = LLM-driven (requires LLM runtime, semantic inference)
- Multiple mature MCPs already provide multi-DB schema inspection, so inspect_schema is removed

**User quote**: "yml生成是不是核心逻辑？ai和mcp只是辅助手段" → Confirmed: YAML template generation is core, AI is auxiliary.
**User quote**: "纯离线用 mcp-server-sqlseed这句话描述的是不是不准确...MCP应该是在线离线都支持吧" → Corrected: boundary is LLM dependency, not online/offline.

### 7.6 Plugin System Stays in Core

**Decision**: `src/sqlseed/plugins/` (hookspecs + manager) stays in core. Only AI-specific mediation moves out.

**Rationale**:
- pluggy is lightweight, doesn't affect core stability
- Plugin system is infrastructure for "external plugins connecting to core"
- Without it, sqlseed-ai/sqlseed-cli cannot integrate

**User quote**: "外部以插件形式接入核心功能来完成数据库的测试数据生成"

---

## 8. Refactoring Checklist

Work items to align code with this document (to be executed in separate branches):

### Phase A: MySQL Removal
- [ ] Clean MySQL mentions in `database/_dialect.py` (comments/docstrings only, no `MySQLDialect` class)
- [ ] Delete `_MYSQL_TYPE_MAP` + `dialect_name == "mysql"` branch in `database/_type_normalizer.py`
- [ ] Delete `if "mysql" in db_url` + `if dialect_name == "mysql"` branches in `database/sqlalchemy_adapter.py`
- [ ] Delete `mysql` optional dep in `pyproject.toml`
- [ ] Delete MySQL references in tests and docs

### Phase B: CLI Extraction
- [ ] Create `plugins/sqlseed-cli/` package with own `pyproject.toml`
- [ ] Move `src/sqlseed/cli/` → `plugins/sqlseed-cli/src/sqlseed_cli/`
- [ ] Move `ai_commands.py` → `plugins/sqlseed-ai/src/sqlseed_ai/cli/`
- [ ] Remove `[project.scripts]` from core `pyproject.toml`
- [ ] Add `cli` optional dep pointing to `sqlseed-cli`
- [ ] Move CLI tests to `plugins/sqlseed-cli/tests/`

### Phase C: AI Code Extraction
- [ ] `core/enrichment.py` stays **entirely** in core (`EnrichmentEngine` is local computation, no AI logic to move)
- [ ] Move `core/plugin_mediator.py` `apply_ai_suggestions()` → `plugins/sqlseed-ai/`
- [ ] Keep `apply_batch_transforms()` + `apply_template_pool()` in core `plugin_mediator.py`
- [ ] Orchestrator calls AI via pluggy hook (`plugins.hook.sqlseed_ai_analyze_table()`)

### Phase D: MCP Scope Narrowing
- [ ] Remove `sqlseed_inspect_schema` tool from mcp-server-sqlseed
- [ ] Remove `sqlseed_gemma4_analyze`, `sqlseed_gemma4_agent_fill`, `sqlseed_list_gemma_models` tools
- [ ] Remove `sqlseed://schema` Resource
- [ ] Keep only `sqlseed_generate_yaml` (rule-driven) + `sqlseed_execute_fill`
- [ ] Move AI MCP tools to `sqlseed-ai[mcp]`

### Phase E: Gemma4 Protocol Abstraction
- [ ] Ensure Gemma4 native function calling is in `analyzer/_tool_calling.py` as protocol implementation
- [ ] Ensure `AIConfig.backend` uses standard backends (no `gemma4`)
- [ ] Ensure `AIConfig.tool_calling_protocol: Literal["gemma4", "openai", "none"]`
- [ ] NO `gemma4/` subdirectory
- [ ] NO post-competition cleanup needed (Gemma4 is long-term backend)

### Phase F: Test Reorganization
- [ ] Core tests stay in `tests/`
- [ ] Create `plugins/sqlseed-cli/tests/`
- [ ] Move AI tests to `plugins/sqlseed-ai/tests/`
- [ ] Move MCP tests to `plugins/mcp-server-sqlseed/tests/`
- [ ] Update CI to run tests per-package

### Phase G: Documentation Sync (Final Step)
- [ ] Update `CLAUDE.md` with all alignment decisions
- [ ] Update `AGENTS.md` with corresponding sections
- [ ] `GEMINI.md` remains pointer to `CLAUDE.md`
- [ ] Run `pytest tests/test_doc_sync.py` to verify consistency

---

## 9. Defense Mechanisms (Anti-Corruption)

Four complementary layers prevent core code corruption and mock self-proving traps:

| Layer | Tool | What It Prevents |
|-------|------|-----------------|
| (a) Architecture contracts | `lint-imports` (3 contracts) | Cross-layer dependency violations |
| (b) Architecture guard tests | `tests/test_architecture.py` (13 tests) | Module boundary / count contract drift |
| (c) Mutation testing | `make mutmut` | Self-proving mock tests (quantified baseline) |
| (d) Doc sync | `tests/test_doc_sync.py` | Documentation vs code count mismatches |

**All 4 must pass before merge.** See `CLAUDE.md` Critical Pitfalls #13-#14 for details.

---

## 10. Gemma4 Long-term Maintenance (No Post-Competition Cleanup)

Gemma4 is a **long-term LLM backend**, NOT competition-only code. There is **NO post-competition cleanup**.

### Gemma5 Transition Procedure

When Gemma5 is released, follow these steps:

1. Check if Gemma5 uses the same 6 special tokens (`<|tool>`, `<|tool_call>`, `<|tool_result>`, etc.)
2. **If same tokens**: Zero code change. Users just update the model name: `model="gemma5:xx"`
3. **If different tokens**: Add `tool_calling_protocol="gemma5"` to `AIConfig.tool_calling_protocol` Literal options, implement the new protocol in `analyzer/_tool_calling.py`
4. Do NOT remove `"gemma4"` from protocol options (backward compatibility)
5. Update `_model_selector.py` to include Gemma5 model entries
6. Run full test suite + `lint-imports` + `make mutmut` to verify no breakage
7. Update `CLAUDE.md` / `AGENTS.md` to add Gemma5 references

**Key**: Gemma4 support is retained indefinitely. Generic AI functionality (analyzer/, refiner.py) continues to work with all backends.
