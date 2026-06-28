# sqlseed Project Alignment Dialog

**Created:** 2026-06-26
**Purpose:** Complete record of the alignment conversation between user and assistant, intended for multi-agent architecture review. This document captures the full dialog trace, user's original requirements, all decision points, and the final architecture decisions.
**Status:** Ready for multi-agent review

---

## 1. Background

### 1.1 Trigger

The user identified a meta-problem: before executing any code-level anti-corruption defenses (mock self-proving trap fixes, mutation testing, etc.), the project's authoritative documentation (CLAUDE.md, AGENTS.md, GEMINI.md) must be aligned with the user's actual requirements. Otherwise, all defense mechanisms would be protecting the wrong things.

### 1.2 User's Insight

> "需要和用户对齐，这样才能保证CLAUDE、AGENTS、GEMINI相关文档和用户需求一致"

The user recognized that:
1. ARCHITECTURE.md was generated as a new file during alignment, but CLAUDE.md and AGENTS.md still contained stale content (MySQL references, CLI as core module, AI in core, etc.)
2. Before synchronizing to CLAUDE.md/AGENTS.md, the alignment decisions themselves need independent review (multi-agent review) to ensure they represent best practices
3. This document captures the full alignment dialog for that review

---

## 2. User's Original Requirements

The user declared 5 core requirements that form the foundation of all architecture decisions:

### 2.1 Core Package Scope

> "sqlseed是一个用于数据库测试库，只专注于为数据库写入合理的测试数据，其他功能不涉及"

sqlseed is a database test data library. It focuses exclusively on writing reasonable test data to databases — nothing else.

### 2.2 AI Plugin Scope

> "sqlseed-ai 是用于ai辅助完成数据库生成的库，它属于sqlseed的一个插件，核心逻辑是完成yml文件的ai生成"

sqlseed-ai is an AI-assisted plugin for sqlseed. Its core logic is AI-powered YAML file generation.

### 2.3 MCP Plugin Scope

> "mcp-server-sqlseed是一个mcp插件，只专注于测试数据生成"

mcp-server-sqlseed is an MCP plugin focused exclusively on test data generation.

### 2.4 Multi-Database Support

> "以上插件要支持多数据库的测试数据生成，目前已经实现2种类型"

Both plugins must support multi-database test data generation. Currently 2 types are implemented.

### 2.5 Microservice-Style Architecture

> "项目整体架构类似于微服务架构，主要的核心功能保持不变...其他功能随着ai的发展可以使用插件的方式快速迭代"

The project architecture resembles microservices: core functionality stays stable, other features evolve rapidly as plugins (especially as AI technology develops).

---

## 3. Alignment Conversation (6 Rounds)

### Round 1: Core Architecture Boundaries

**User's key statements:**
- MCP tools: "gemma4相关功能我是知道的，但是从我之前的描述来看，你觉得放在这个mcp-server-sqlseed中合适吗...schema 检查首先要调研一下是否有相关的mcp功能是支持"
- Core AI code: "这一层应该是涉及到了核心能力，当前需要保证用户入口支持：1.在没有sqlseed-ai的情况下，可以手动配置yml文件...2.一定要支持python api的调用...3.需要支持当下流行的CLI终端...4.cli、ai、MCP是可选功能...5.核心能力保证不变动"
- Multi-DB status: "SQLite 是默认内置，PostgreSQL 是已完成的扩展；MySql暂时不添加，保证代码的整洁性...所以相关的内容需要删除"
- ai-suggest location: "因为涉及到有部分用户不使用CLI功能，只使用Python代码功能，所以CLI为可选项，可以变为插件形式接入；ai也是，因为ai需要联网配置api，核心功能要保证离线也可以正常使用"

**Decisions from Round 1:**
- MCP gemma4 tools don't belong in mcp-server-sqlseed (should be in sqlseed-ai)
- Schema inspection should be researched (later confirmed: use existing mature MCPs)
- Core entry points: Python API (required) + manual YAML (required) + CLI (optional) + AI (optional) + MCP (optional)
- MySQL: completely remove
- CLI: extract to plugin form
- AI: must be plugin (requires network)

---

### Round 2: Plugin Release Strategy

**User's key statements:**
- CLI install: "你觉得怎样比较好从最优设计来看？因为我这里不是很懂...核心功能要保证长期稳定"
- Plugin system location: "这个涉及到明确的边界定义了，我从用户的使用角度（无感使用），核心功能直接sqlseed，想要安装特定的功能直接pip install sqlseed[需要安装的功能]"
- Mediator split: "我不太清楚这3个功能是什么作用，按照最佳实践来设计"
- MySQL deletion scope: Selected "完全删除" (complete deletion)

**Decisions from Round 2:**
- Plugin system (pluggy hookspecs + manager) stays in core package as infrastructure
- `core/plugin_mediator.py` keeps generic methods (`apply_batch_transforms`, `apply_template_pool`); AI-specific `apply_ai_suggestions` moves to sqlseed-ai
- MySQL: complete deletion (not just disabling)
- User install pattern: `pip install sqlseed[feature]`

---

### Round 3: AI Enrichment Boundary & Gemma4 Research

**User's key statements:**
- Enrichment split: "使用AI插件的本质是需要网络进行调用...但是核心功能一定要保证离线可以正常使用不依赖外部网络。你可以按照最佳实践去帮我判断一下"
- Gemma4: "相关功能我建议调研一下...1.https://github.com/gdgshanghai/Gemma4-Hackathon-ShangHai 这个是比赛的参考链接，当前我是要参加比赛...注意：首先要保证项目整体是纯净的，不能因为比赛所涉及到的代码而污染整个项目"
- MCP generate_yaml: "保证MCP功能的专注，只做测试数据生成的相关功能"
- Additional: "你还可以对我进行相关的提问，保证每一轮对话的问题有所收敛；但是不要因为收敛问题而减少提问问题的数量"

**Decisions from Round 3:**
- `core/enrichment.py`: keep `detect_enum_columns()` (local computation) in core; move `apply_ai_enrichment()` to sqlseed-ai
- Gemma4: needs research (later confirmed as both online and offline capable)
- MCP: focus exclusively on test data generation (no schema inspection)
- Schema inspection: handled by existing MCPs (mcp-database-server, mcp-db-analyzer)

---

### Round 4: Gemma4 Isolation & Test Organization

**User's key statements:**
- Gemma4 isolation: "我觉得偏向于1和3，纠结选择哪一个比较好，是最佳实践对于整个项目来说"
- AI MCP interface: Selected "sqlseed-ai 自带 MCP"
- CLI entry_points: "你说这个问题我又纠结了，纠结的点还是在于使用场景...如果按照核心功能可以离线使用的标准来看，sqlseed作为指令确实也没什么问题...所以还是需要你帮我判断一下...因为在以上2种情况来看，2就是1的子集了，我说的对吧？"
- Test organization: Selected "分离测试" (separated tests)

**Decisions from Round 4:**
- Gemma4 code isolated for easy removal (LATER REVISED in Round 6 — see below)
- sqlseed-ai provides its own MCP interface (`pip install sqlseed-ai[mcp]`)
- CLI: completely separate plugin (no `[project.scripts]` in core)
- Tests: core tests stay in `tests/`, plugin tests move to `plugins/*/tests/`

---

### Round 5: Document Sync Strategy

**User's key statements:**
- "我认为当前时机有点不对，因为生成的文档，没有进行文档的项目评审；我的想法是，使用其他的智能体，结合你给我生成的文档和当前项目进行代码评审，保证当前设计为最佳实践"
- "应该是没有问题了，我的想法是把咱们之前从我开始要求你和我进行项目对齐的对话，生成一份文档；之后对这个文档，我会使用其他多智能体进行评审"
- "如果你还有相关需要和我对齐的，可以继续询问"

**Decisions from Round 5:**
- Do NOT directly sync to CLAUDE.md/AGENTS.md yet
- Generate this alignment dialog document first
- User will use other AI agents to review this document against the actual project
- After review confirms best practices, then sync to CLAUDE.md/AGENTS.md/GEMINI.md

---

### Round 6: Gemma4 Long-term Position & MCP Boundary Refinement

**User's key statements:**
- Gemma4: "Gemma4这个功能放在哪个位置，取决于做的是是否好；我认为如果做的很好的情况下，是不是完全可以作为插件去使用；比如我需要使用到gemma4的情况下安装插件即可，如果不需要，不安装也不会有影响；但是这里又涉及到了后续版本的维护性相关问题，比如后续如果出了新版本gemma5怎么办？后续怎么处理。相关gemma4问题取决于是否想要长期保留"
- sqlseed-cli: "完全独立包，这个没有问题"
- MCP boundary: "mcp-server-sqlseed和sqlseed-ai的交集部分sqlseed-ai[mcp]感觉还是有点模糊，在我看来yml生成是不是核心逻辑？ai和mcp只是辅助手段"
- MCP online/offline: "纯离线用 mcp-server-sqlseed这句话描述的是不是不准确，因为如果我想要CLI接入MCP的情况下，它一般为在线吧，比如claude code接入MCP，所以MCP应该是在线离线都支持吧？"

**Gemma4 Research Results:**
- Gemma4 is Apache 2.0, no MAU limits — legally viable long-term
- Gemma4 supports both online (Google AI Studio) and offline (Ollama/LM Studio) deployment
- Gemma4 has Native Function Calling via 6 special tokens (`<|tool>`, `<|tool_call>`, `<|tool_result>`, etc.)
- Multiple model sizes: E2B (2.3B), E4B (4.5B), 26B MoE, 31B Dense

**Decisions from Round 6:**

1. **Gemma4 as Long-term LLM Backend** (REVISED from Round 4's "isolation for removal"):
   - Gemma4 is NOT competition-only code. It is a long-term supported LLM backend.
   - No `sqlseed_ai/gemma4/` subdirectory (avoids implying removability).
   - Gemma4 native function calling lives in `analyzer/_tool_calling.py` as a **protocol implementation** (`tool_calling_protocol="gemma4"`), alongside `"openai"` and `"none"`.
   - Gemma4 accessed via standard backends: `backend="ollama"` + `model="gemma4:26b"`, or `backend="google_ai_studio"` + `model="gemma-4-..."`.
   - No `backend="gemma4"` config — Gemma4 is a model, not a backend.
   - **Gemma5 transition**: If Gemma5 keeps the same 6 special tokens, zero code change. If Gemma5 changes tokens, add `tool_calling_protocol="gemma5"` — no removal of `"gemma4"` needed (backward compatible).

2. **MCP Boundary Refinement** (REVISED from Round 4's "online/offline" split):
   - YAML template generation is a **core capability** (uses `ColumnMapper` with 74 exact rules + 27 patterns), not an AI feature.
   - **Boundary**: The dividing line between the two MCPs is "whether LLM runtime is required", NOT "online/offline" (MCP protocol is neutral to deployment mode).
   - **mcp-server-sqlseed**: `sqlseed_generate_yaml` (rule-driven, no LLM) + `sqlseed_execute_fill`. Exposes core capabilities. Works regardless of network.
   - **sqlseed-ai[mcp]**: `sqlseed_ai_generate_yaml` (LLM-driven). Exposes AI plugin capabilities. Requires LLM runtime (online API or local Ollama/LM Studio).
   - **Intersection definition** (both generate YAML): mcp-server-sqlseed = rule-driven (offline-capable, deterministic, good for simple schemas); sqlseed-ai[mcp] = LLM-driven (requires LLM, good for complex schemas requiring semantic inference).

3. **sqlseed-cli Release**: Confirmed as completely independent package (independent pyproject.toml, independent version, independent release). Consistent with sqlseed-ai and mcp-server-sqlseed.

---

## 4. Final Architecture Decisions (8 Items)

### Decision 1: Core Package Stability

The core package (`sqlseed`) must remain stable and offline-capable. It contains:
- Python API: `fill`, `connect`, `preview`, `fill_from_config`, `load_config`
- Core logic: orchestrator, mapper, schema, relation, column_dag, expression, constraints, transform, result, stream, unique_adjuster
- Generators: faker (required), mimesis (optional), base (type-routing only)
- Database adapters: SQLAlchemy (required, SQLite + PostgreSQL), RawSQLite (test-only)
- Plugin infrastructure: pluggy hookspecs + manager (stays in core as infrastructure)
- Config: Pydantic models, YAML loader, SnapshotManager
- Utils: sql_safe, logger, metrics, progress, paths (no internal deps)

### Decision 2: CLI as Completely Independent Package

- `plugins/sqlseed-cli/` with own `pyproject.toml`, independent version, independent release
- Core package has NO `[project.scripts]`
- `pip install sqlseed-cli` provides the `sqlseed` command
- CLI depends on: `sqlseed` (core) + `click` + `rich`
- Consistent with sqlseed-ai and mcp-server-sqlseed (all independent packages)

### Decision 3: AI Code Completely in Plugin

- All AI-related code moves to `plugins/sqlseed-ai/`
- Core has zero AI logic
- `core/enrichment.py` keeps only `detect_enum_columns()` (local computation)
- `core/plugin_mediator.py` keeps only generic methods (`apply_batch_transforms`, `apply_template_pool`)
- AI-specific `apply_ai_suggestions()` and `apply_ai_enrichment()` move to sqlseed-ai
- Orchestrator calls AI via pluggy hook (`plugins.hook.sqlseed_ai_analyze_table()`)

### Decision 4: Gemma4 as Long-term LLM Backend

- Gemma4 is NOT competition-only code — it is a long-term supported LLM backend
- No `gemma4/` subdirectory (avoids implying removability)
- Native function calling is a pluggable `tool_calling_protocol` in `analyzer/_tool_calling.py`
- `AIConfig.backend` uses `"google_ai_studio"` / `"ollama"` / `"lm_studio"` / `"openai"` (NO `"gemma4"`)
- Gemma4 accessed via standard backends + model name (e.g., `backend="ollama"`, `model="gemma4:26b"`)
- Gemma5 transition: add new protocol option if needed (backward compatible)

### Decision 5: MySQL Completely Removed

- Delete MySQL branches in `database/_dialect.py`
- Delete MySQL types in `database/_type_normalizer.py`
- Delete `mysql` optional dep in `pyproject.toml`
- Delete MySQL references in tests and docs
- Rationale: only SQLite + PostgreSQL are implemented; MySQL deferred until PostgreSQL fully validated

### Decision 6: MCP Boundary by LLM Dependency

- **mcp-server-sqlseed**: `sqlseed_generate_yaml` (rule-driven, no LLM) + `sqlseed_execute_fill`
  - Exposes core capabilities via MCP
  - Does NOT depend on any LLM
  - Works regardless of network (local stdio or remote HTTP)
- **sqlseed-ai[mcp]**: `sqlseed_ai_generate_yaml` (LLM-driven)
  - Exposes AI plugin capabilities via MCP
  - Requires LLM runtime (online API or local Ollama/LM Studio)
- **Boundary**: "whether LLM runtime is required", NOT "online/offline"
- **Intersection**: both generate YAML, but mcp-server-sqlseed uses rules (deterministic), sqlseed-ai[mcp] uses LLM (semantic inference)
- Schema inspection removed (use existing mcp-database-server / mcp-db-analyzer)

### Decision 7: YAML Template Generation is Core Capability

- YAML template generation (using `ColumnMapper` with 74 exact rules + 27 patterns) is a **core capability**
- AI YAML generation is an **enhancement** for complex schemas
- This is why `sqlseed_generate_yaml` belongs in mcp-server-sqlseed (exposing core), not sqlseed-ai

### Decision 8: Plugin System Stays in Core

- `src/sqlseed/plugins/` (hookspecs + manager) stays in core package
- Only AI-specific mediation moves out to sqlseed-ai
- pluggy is lightweight, doesn't affect core stability
- Plugin system is infrastructure for "external plugins connecting to core"
- Without it, sqlseed-ai/sqlseed-cli cannot integrate

---

## 5. Installation Matrix

| Use Case | Install Command | What You Get |
|----------|----------------|--------------|
| Python API only (offline) | `pip install sqlseed` | `from sqlseed import fill` |
| + CLI | `pip install sqlseed-cli` | `sqlseed` command |
| + AI YAML generation | `pip install sqlseed-ai` | `sqlseed ai-suggest` + Gemma4 support |
| + PostgreSQL | `pip install sqlseed[postgres]` | PostgreSQL support |
| + mimesis (high-perf) | `pip install sqlseed[mimesis]` | MimesisProvider |
| + MCP server (core capabilities) | `pip install mcp-server-sqlseed` | MCP tools for rule-based YAML + fill |
| + AI MCP | `pip install sqlseed-ai[mcp]` | AI MCP tools for LLM-driven YAML |
| Everything | Install all above | All optional features |

---

## 6. Database Support

| Database | Status | Adapter |
|----------|--------|---------|
| SQLite | ✅ Default (built-in) | `SQLAlchemyAdapter` |
| PostgreSQL | ✅ Implemented (extension) | `SQLAlchemyAdapter` + `psycopg` |
| MySQL | ❌ Removed (deferred until PostgreSQL fully validated) | — |

---

## 7. Review Focus Points for Multi-Agent Evaluation

When reviewing this document, multi-agent reviewers should focus on:

### 7.1 Architecture Boundary Correctness

- Is the "LLM dependency" boundary between mcp-server-sqlseed and sqlseed-ai[mcp] the right dividing line?
- Is YAML template generation correctly classified as a core capability (rule-driven) vs AI enhancement (LLM-driven)?
- Are there any capabilities that don't cleanly fit the "core vs plugin" split?

### 7.2 Gemma4 Long-term Viability

- Is treating Gemma4 as a long-term LLM backend (vs competition-only code) the right call?
- Is the `tool_calling_protocol` abstraction (vs `backend="gemma4"`) the right design for Gemma5 transition?
- Are there risks in keeping Gemma4 native function calling code long-term?

### 7.3 Plugin Independence

- Is the completely independent package model (each plugin has own pyproject.toml + version) the best practice?
- How should version compatibility between sqlseed core and plugins be managed?
- Should there be a compatibility matrix or version constraints?

### 7.4 Core Stability

- Does keeping pluggy plugin system in core violate "core stability" principle?
- Is `detect_enum_columns()` truly local computation, or does it have hidden AI dependencies?
- Are there any other core modules that should move to plugins?

### 7.5 MCP Ecosystem Positioning

- Is the MCP scope (no schema inspection) correct given existing mcp-database-server / mcp-db-analyzer?
- Should mcp-server-sqlseed and sqlseed-ai[mcp] be merged or kept separate?
- Is the intersection definition (both generate YAML, but rule-driven vs LLM-driven) clear enough to prevent code drift?

---

## 8. Known Issues

### 8.1 ARCHITECTURE.md Update (Resolved)

Earlier editing sessions encountered file system recovery issues where Edit tool operations reported success but content reverted. This was resolved by rewriting the entire file with the Write tool in a single pass.

All sections now reflect the Round 6 alignment decisions:
- Section 3.3 (sqlseed-ai plugin): ✅ Gemma4 as long-term backend, `tool_calling_protocol` abstraction
- Section 3.4 (mcp-server-sqlseed): ✅ MCP boundary by LLM dependency
- Section 7.4 (Gemma4 decision): ✅ "Gemma4 as Long-term LLM Backend"
- Section 7.5 (MCP decision): ✅ "MCP Scope and Boundary" (no longer "MCP Scope Narrowed")
- Phase E: ✅ "Gemma4 Protocol Abstraction" (no longer "Gemma4 Isolation")
- Section 10: ✅ "Gemma4 Long-term Maintenance (No Post-Competition Cleanup)"

### 8.2 CLAUDE.md / AGENTS.md / GEMINI.md Not Yet Synced

Per user's Round 5 decision:
- These files will NOT be updated until multi-agent review confirms the design is best practice
- After review, alignment decisions will be synchronized to all three files
- GEMINI.md is a pointer to CLAUDE.md (single source of truth pattern)

---

## 9. Refactoring Roadmap (Post-Review)

After multi-agent review confirms the design, execute in separate branches:

### Phase A: MySQL Removal
- Delete MySQL branches in `database/_dialect.py`
- Delete MySQL types in `database/_type_normalizer.py`
- Delete `mysql` optional dep in `pyproject.toml`
- Delete MySQL references in tests and docs

### Phase B: CLI Extraction
- Create `plugins/sqlseed-cli/` package with own `pyproject.toml`
- Move `src/sqlseed/cli/` → `plugins/sqlseed-cli/src/sqlseed_cli/`
- Move `ai_commands.py` → `plugins/sqlseed-ai/src/sqlseed_ai/cli/`
- Remove `[project.scripts]` from core `pyproject.toml`
- Move CLI tests to `plugins/sqlseed-cli/tests/`

### Phase C: AI Code Extraction
- Move `core/enrichment.py` `apply_ai_enrichment()` → `plugins/sqlseed-ai/`
- Move `core/plugin_mediator.py` `apply_ai_suggestions()` → `plugins/sqlseed-ai/`
- Keep `detect_enum_columns()` in core `enrichment.py`
- Keep `apply_batch_transforms()` + `apply_template_pool()` in core `plugin_mediator.py`
- Orchestrator calls AI via pluggy hook

### Phase D: MCP Scope Narrowing
- Remove `sqlseed_inspect_schema` tool from mcp-server-sqlseed
- Remove `sqlseed_gemma4_analyze`, `sqlseed_gemma4_agent_fill`, `sqlseed_list_gemma_models` tools
- Remove `sqlseed://schema` Resource
- Keep only `sqlseed_generate_yaml` (rule-driven) + `sqlseed_execute_fill`
- Move AI MCP tools to `sqlseed-ai[mcp]`

### Phase E: Gemma4 Protocol Abstraction
- Ensure Gemma4 native function calling is in `analyzer/_tool_calling.py` as protocol implementation
- Ensure `AIConfig.backend` uses standard backends (no `gemma4`)
- Ensure `AIConfig.tool_calling_protocol: Literal["gemma4", "openai", "none"]`
- NO `gemma4/` subdirectory
- NO post-competition cleanup needed (Gemma4 is long-term backend)

### Phase F: Test Reorganization
- Core tests stay in `tests/`
- Create `plugins/sqlseed-cli/tests/`
- Move AI tests to `plugins/sqlseed-ai/tests/`
- Move MCP tests to `plugins/mcp-server-sqlseed/tests/`
- Update CI to run tests per-package

### Phase G: Documentation Sync (Final Step)
- Update CLAUDE.md with all alignment decisions
- Update AGENTS.md with corresponding sections
- GEMINI.md remains pointer to CLAUDE.md
- Run `pytest tests/test_doc_sync.py` to verify consistency

---

## 10. Glossary

| Term | Definition |
|------|-----------|
| Core capability | Functionality that works offline without LLM, part of sqlseed core package |
| Plugin capability | Functionality that requires external dependencies (CLI libs, LLM, MCP protocol) |
| LLM runtime | An active LLM service (online API like Google AI Studio, or local service like Ollama/LM Studio) |
| Native Function Calling | Gemma4's built-in tool calling via 6 special tokens (`<|tool>`, `<|tool_call>`, `<|tool_result>`, etc.) |
| tool_calling_protocol | Configurable protocol in AIConfig for native function calling (`"gemma4"`, `"openai"`, `"none"`) |
| Rule-driven YAML | YAML generation using `ColumnMapper` (74 exact rules + 27 patterns), no LLM, deterministic |
| LLM-driven YAML | YAML generation using LLM analysis of schema, requires LLM runtime, semantic inference |
