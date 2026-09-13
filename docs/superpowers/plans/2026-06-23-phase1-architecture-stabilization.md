# Phase 1: Architecture Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize the codebase architecture by fixing CLI circular dependency (H4), splitting analyzer.py (H3), and splitting DataOrchestrator (H1) using worktree competition + fusion methodology.

**Architecture:** Serial worktree competition — for each task, Agent A and Agent B work independently in separate worktrees on the same task, Agent C fuses the best of both approaches, then merges to feat/multi-db-support.

**Tech Stack:** Python 3.10+, Click (CLI), SQLAlchemy, OpenAI SDK (AI plugin), ruff, mypy, pytest

**Design Spec:** `docs/superpowers/specs/2026-06-23-codebase-optimization-design.md`

---

## File Structure

### H4: CLI Circular Dependency Fix
- Modify: `src/sqlseed/cli/main.py` (remove try/except ImportError at end, move _sanitize_table_config)
- Modify: `src/sqlseed/cli/ai_commands.py` (fix import of cli group)
- Create: `src/sqlseed/cli/_utils.py` (shared CLI utilities, including _sanitize_table_config)
- Test: `tests/test_cli.py` (verify all commands still work)

### H3: analyzer.py Split
- Create: `plugins/sqlseed-ai/src/sqlseed_ai/analyzer/` package directory
- Create: `plugins/sqlseed-ai/src/sqlseed_ai/analyzer/__init__.py` (public API)
- Move: Content from `analyzer.py` into sub-modules
- Delete: `plugins/sqlseed-ai/src/sqlseed_ai/analyzer.py` (replaced by package)
- Test: `plugins/sqlseed-ai/tests/test_ai_plugin.py` (verify SchemaAnalyzer API unchanged)

### H1: DataOrchestrator Split
- Modify: `src/sqlseed/core/orchestrator.py` (reduce to < 200 lines, orchestration only)
- Create: `src/sqlseed/core/_connection.py` or equivalent (connection lifecycle)
- Create: `src/sqlseed/core/_spec_resolver.py` or equivalent (spec preparation)
- Create: `src/sqlseed/core/_batch_writer.py` or equivalent (batch generation + insert)
- Test: `tests/test_orchestrator.py` (verify DataOrchestrator API unchanged)

---

## Task 1: H4 — CLI Circular Dependency Fix

**Files:**
- Modify: `src/sqlseed/cli/main.py` (lines 482-490, 497-522)
- Modify: `src/sqlseed/cli/ai_commands.py` (lines 19, 269-273)
- Create: `src/sqlseed/cli/_utils.py`
- Test: `tests/test_cli.py`

### Step 1: Create backup branch

- [ ] **Step 1.1: Create Phase 1 backup**

```powershell
git branch feat/multi-db-support-backup-p1
```

- [ ] **Step 1.2: Create worktrees for Agent A and Agent B**

```powershell
git worktree add ../sqlseed-worktree-a -b feat/multi-db-support-h4-agent-a
git worktree add ../sqlseed-worktree-b -b feat/multi-db-support-h4-agent-b
```

- [ ] **Step 1.3: Verify worktrees created**

```powershell
git worktree list
```
Expected: 3 entries (main + worktree-a + worktree-b)

### Step 2: Agent A — Plugin-style command registration

**Working directory:** `c:\Users\14435\Desktop\sqlseed-worktree-a`

**Approach:** Create `cli/_utils.py` for shared utilities, use Click's command group pattern.

- [ ] **Step 2.1: Create `src/sqlseed/cli/_utils.py`**

```python
"""Shared CLI utility functions."""

from __future__ import annotations

import re
from typing import Any


def sanitize_table_config(config_dict: dict[str, Any]) -> None:
    """Remove leading dots/colons from table and column names in config dict."""
    name = config_dict.get("name")
    if isinstance(name, str):
        config_dict["name"] = re.sub(r"^[:.]+", "", name)
    for col in config_dict.get("columns", []):
        if isinstance(col, dict):
            col_name = col.get("name")
            if isinstance(col_name, str):
                col["name"] = re.sub(r"^[:.]+", "", col_name)
```

- [ ] **Step 2.2: Update `src/sqlseed/cli/main.py`**

Remove `_sanitize_table_config` function (lines 482-490).
Remove the try/except ImportError block at end (lines 497-518).
Add import at top: `from sqlseed.cli._utils import sanitize_table_config`
Keep backward compatibility: add `_sanitize_table_config = sanitize_table_config` alias.

- [ ] **Step 2.3: Update `src/sqlseed/cli/ai_commands.py`**

Change line 19 from `from sqlseed.cli.main import cli` to:
```python
from sqlseed.cli.main import cli  # noqa: I001 - cli group defined before this import runs
```
Change line 271 from `from sqlseed.cli.main import _sanitize_table_config` to:
```python
from sqlseed.cli._utils import sanitize_table_config
```
Update line 273: `sanitize_table_config(result)` instead of `_sanitize_table_config(result)`.

- [ ] **Step 2.4: Update `src/sqlseed/cli/__init__.py` to register AI commands**

```python
"""sqlseed CLI package."""

from sqlseed.cli.main import cli

# Register AI commands if sqlseed-ai is installed.
try:
    import sqlseed.cli.ai_commands  # noqa: F401
except ImportError:
    pass

__all__ = ["cli"]
```

- [ ] **Step 2.5: Agent A self-check**

```powershell
cd c:\Users\14435\Desktop\sqlseed-worktree-a
ruff check .
mypy src plugins
```
Expected: All checks pass.

### Step 3: Agent B — Click command group + deferred import

**Working directory:** `c:\Users\14435\Desktop\sqlseed-worktree-b`

**Approach:** Move `_sanitize_table_config` into `ai_commands.py` itself, use `cli.add_command()` pattern.

- [ ] **Step 3.1: Update `src/sqlseed/cli/ai_commands.py`**

Add `sanitize_table_config` function directly in `ai_commands.py` (copy from main.py lines 482-490).
Remove the lazy import at line 271.
Use `sanitize_table_config` directly at line 273.

Change line 19 from `from sqlseed.cli.main import cli` to:
```python
import click
# cli group will be passed via add_command, avoiding circular import
```

Define `ai_suggest` as a standalone Click command, then register it:
```python
@click.command("ai-suggest")
# ... existing options ...
def ai_suggest(...):
    ...

# Registration function called from __init__.py
def register_commands(cli_group):
    cli_group.add_command(ai_suggest)
```

- [ ] **Step 3.2: Update `src/sqlseed/cli/main.py`**

Remove `_sanitize_table_config` function (lines 482-490).
Remove the try/except ImportError block at end (lines 497-518).

- [ ] **Step 3.3: Update `src/sqlseed/cli/__init__.py`**

```python
"""sqlseed CLI package."""

from sqlseed.cli.main import cli

# Register AI commands if sqlseed-ai is installed.
try:
    from sqlseed.cli.ai_commands import register_commands
    register_commands(cli)
except ImportError:
    pass

__all__ = ["cli"]
```

- [ ] **Step 3.4: Agent B self-check**

```powershell
cd c:\Users\14435\Desktop\sqlseed-worktree-b
ruff check .
mypy src plugins
```
Expected: All checks pass.

### Step 4: Agent C — Fusion

**Working directory:** `c:\Users\14435\Desktop\sqlseed\` (main)

- [ ] **Step 4.1: Compare both implementations**

```powershell
git diff feat/multi-db-support-h4-agent-a -- src/sqlseed/cli/
git diff feat/multi-db-support-h4-agent-b -- src/sqlseed/cli/
git diff feat/multi-db-support-h4-agent-a feat/multi-db-support-h4-agent-b -- src/sqlseed/cli/
```

- [ ] **Step 4.2: Evaluate and choose fusion strategy**

Assess:
- Agent A: `_utils.py` with shared utilities + `__init__.py` registration → cleaner separation
- Agent B: `register_commands()` pattern + self-contained `ai_commands.py` → more explicit registration

**Fusion decision criteria:**
- If Agent A's `_utils.py` approach is cleaner → use A, cherry-pick B's `register_commands` pattern
- If Agent B's `register_commands` is more explicit → use B, cherry-pick A's `_utils.py`
- If both have merits → combine: `_utils.py` for shared utils + `register_commands` for explicit registration

- [ ] **Step 4.3: Apply fused result**

Create the fused version in the main working directory. Ensure:
- `cli/_utils.py` exists with `sanitize_table_config`
- `cli/__init__.py` registers AI commands via `register_commands(cli)` or import
- `cli/main.py` has no try/except ImportError at end
- `cli/ai_commands.py` uses `register_commands` pattern or direct import

- [ ] **Step 4.4: Stage 2 validation (fused result)**

```powershell
cd c:\Users\14435\Desktop\sqlseed
ruff check .
mypy src plugins
python -m pytest tests/test_cli.py --tb=short -q
```
Expected: All checks pass.

### Step 5: Merge and final validation

- [ ] **Step 5.1: Commit fused result**

```powershell
git add src/sqlseed/cli/
git commit -m "refactor: fix CLI circular dependency (H4) - move shared utils to _utils.py, use explicit command registration"
```

- [ ] **Step 5.2: Stage 3 validation**

```powershell
ruff check .
mypy src plugins
python -m pytest --tb=short -q
python -c "from sqlseed.cli.main import cli; cli(['--help'])"
python -c "from sqlseed import fill, connect, fill_from_config, preview"
```
Expected: All checks pass, CLI --help works, public API unchanged.

- [ ] **Step 5.3: Clean up worktrees**

```powershell
git worktree remove ../sqlseed-worktree-a
git worktree remove ../sqlseed-worktree-b
git branch -D feat/multi-db-support-h4-agent-a feat/multi-db-support-h4-agent-b
git worktree list
```
Expected: Only main working directory shown.

---

## Task 2: H3 — analyzer.py Split

**Files:**
- Create: `plugins/sqlseed-ai/src/sqlseed_ai/analyzer/` package
- Create: `plugins/sqlseed-ai/src/sqlseed_ai/analyzer/__init__.py`
- Move: `plugins/sqlseed-ai/src/sqlseed_ai/analyzer.py` content into sub-modules
- Delete: `plugins/sqlseed-ai/src/sqlseed_ai/analyzer.py`
- Test: `plugins/sqlseed-ai/tests/test_ai_plugin.py`

### Step 6: Create worktrees for H3

- [ ] **Step 6.1: Create worktrees**

```powershell
git worktree add ../sqlseed-worktree-a -b feat/multi-db-support-h3-agent-a
git worktree add ../sqlseed-worktree-b -b feat/multi-db-support-h3-agent-b
```

### Step 7: Agent A — Split by function

**Working directory:** `c:\Users\14435\Desktop\sqlseed-worktree-a`

**Approach:** Split `analyzer.py` (793 lines) into functional sub-modules.

- [ ] **Step 7.1: Create package structure**

```
plugins/sqlseed-ai/src/sqlseed_ai/analyzer/
├── __init__.py          # Public API: SchemaAnalyzer
├── _caller.py           # LLM call + model fallback (_call_with_fallback, _call_llm_once, _find_local_fallback_model)
├── _streaming.py        # Streaming processing (call_llm_streaming, _call_llm_streaming_once, _collect_stream_chunks, _send_llm_request, _send_with_json_mode)
├── _tool_calling.py     # Tool calling (_try_tool_calling, _extract_tool_call_result)
├── _context.py          # Context building (build_initial_messages, _build_context, _append_columns_info, _append_indexes_info, _append_distribution_info)
└── _json_parser.py      # JSON parsing (_parse_json_response, analyze_table_from_ctx)
```

- [ ] **Step 7.2: Implement `__init__.py`**

```python
"""SchemaAnalyzer package — LLM-powered schema analysis."""

from __future__ import annotations

from sqlseed_ai.analyzer._core import SchemaAnalyzer

__all__ = ["SchemaAnalyzer"]
```

- [ ] **Step 7.3: Move code into sub-modules**

Each sub-module gets the relevant methods from the original `analyzer.py`.
`SchemaAnalyzer` class in `_core.py` (or `__init__.py`) imports and delegates to sub-modules.

**Key constraint:** `from sqlseed_ai.analyzer import SchemaAnalyzer` must still work.
**Key constraint:** All public method signatures must remain unchanged.

- [ ] **Step 7.4: Delete original `analyzer.py`**

```powershell
git rm plugins/sqlseed-ai/src/sqlseed_ai/analyzer.py
```

- [ ] **Step 7.5: Agent A self-check**

```powershell
cd c:\Users\14435\Desktop\sqlseed-worktree-a
ruff check .
mypy src plugins
python -c "from sqlseed_ai.analyzer import SchemaAnalyzer; print('OK')"
```
Expected: All checks pass, import works.

### Step 8: Agent B — Split by responsibility

**Working directory:** `c:\Users\14435\Desktop\sqlseed-worktree-b`

**Approach:** Split `analyzer.py` (793 lines) into responsibility-based sub-modules.

- [ ] **Step 8.1: Create package structure**

```
plugins/sqlseed-ai/src/sqlseed_ai/analyzer/
├── __init__.py          # SchemaAnalyzer main class (orchestration, < 200 lines)
├── _llm_backend.py      # LLM backend management (call + fallback: _call_with_fallback, _call_llm_once, _find_local_fallback_model, _build_llm_kwargs, _create_with_reasoning_fallback)
├── _response_handler.py # Response handling (streaming + non-streaming + JSON: call_llm, call_llm_streaming, _call_llm_streaming_once, _collect_stream_chunks, _send_llm_request, _send_with_json_mode, _parse_json_response)
└── _schema_tools.py     # Schema tools (tool calling + context: _try_tool_calling, _extract_tool_call_result, build_initial_messages, _build_context, _append_*, analyze_table_from_ctx, generate_template_values)
```

- [ ] **Step 8.2: Implement `__init__.py` with SchemaAnalyzer class**

The main `SchemaAnalyzer` class lives in `__init__.py` and delegates to sub-modules.
Keep it under 200 lines — it should only orchestrate, not implement details.

- [ ] **Step 8.3: Move code into sub-modules**

Group methods by responsibility:
- `_llm_backend.py`: LLM client creation, model fallback, kwargs building
- `_response_handler.py`: All streaming/non-streaming response processing, JSON parsing
- `_schema_tools.py`: Tool calling, context building, schema analysis entry point

- [ ] **Step 8.4: Delete original `analyzer.py`**

```powershell
git rm plugins/sqlseed-ai/src/sqlseed_ai/analyzer.py
```

- [ ] **Step 8.5: Agent B self-check**

```powershell
cd c:\Users\14435\Desktop\sqlseed-worktree-b
ruff check .
mypy src plugins
python -c "from sqlseed_ai.analyzer import SchemaAnalyzer; print('OK')"
```
Expected: All checks pass, import works.

### Step 9: Agent C — Fusion

- [ ] **Step 9.1: Compare both implementations**

```powershell
git diff feat/multi-db-support-h3-agent-a -- plugins/sqlseed-ai/
git diff feat/multi-db-support-h3-agent-b -- plugins/sqlseed-ai/
```

- [ ] **Step 9.2: Evaluate and choose fusion strategy**

Assess:
- Agent A: 6 modules by function (caller, streaming, tool_calling, context, json_parser, __init__)
- Agent B: 4 modules by responsibility (llm_backend, response_handler, schema_tools, __init__)

**Fusion decision criteria:**
- Module boundary clarity: which split has more cohesive modules?
- Testability: which split makes individual components easier to test?
- Import simplicity: which split has cleaner import graph?
- Choose the split with better cohesion, cherry-pick improvements from the other

- [ ] **Step 9.3: Apply fused result**

Create the fused version in the main working directory.

- [ ] **Step 9.4: Stage 2 validation**

```powershell
cd c:\Users\14435\Desktop\sqlseed
ruff check .
mypy src plugins
python -m pytest plugins/sqlseed-ai/tests/ --tb=short -q
python -c "from sqlseed_ai.analyzer import SchemaAnalyzer; sa = SchemaAnalyzer(); print('OK')"
```
Expected: All checks pass.

### Step 10: Merge and final validation

- [ ] **Step 10.1: Commit fused result**

```powershell
git add plugins/sqlseed-ai/
git commit -m "refactor: split analyzer.py into focused sub-modules (H3) - 793 lines -> package with cohesive modules"
```

- [ ] **Step 10.2: Stage 3 validation**

```powershell
ruff check .
mypy src plugins
python -m pytest --tb=short -q
python -c "from sqlseed_ai.analyzer import SchemaAnalyzer"
```
Expected: All checks pass.

- [ ] **Step 10.3: Clean up worktrees**

```powershell
git worktree remove ../sqlseed-worktree-a
git worktree remove ../sqlseed-worktree-b
git branch -D feat/multi-db-support-h3-agent-a feat/multi-db-support-h3-agent-b
git worktree list
```

---

## Task 3: H1 — DataOrchestrator Split

**Files:**
- Modify: `src/sqlseed/core/orchestrator.py` (761 → < 200 lines)
- Create: `src/sqlseed/core/_connection.py` or equivalent
- Create: `src/sqlseed/core/_spec_resolver.py` or equivalent
- Create: `src/sqlseed/core/_batch_writer.py` or equivalent
- Test: `tests/test_orchestrator.py`

### Step 11: Create worktrees for H1

- [ ] **Step 11.1: Create worktrees**

```powershell
git worktree add ../sqlseed-worktree-a -b feat/multi-db-support-h1-agent-a
git worktree add ../sqlseed-worktree-b -b feat/multi-db-support-h1-agent-b
```

### Step 12: Agent A — Split by lifecycle

**Working directory:** `c:\Users\14435\Desktop\sqlseed-worktree-a`

**Approach:** Split `orchestrator.py` (761 lines) by lifecycle phases.

- [ ] **Step 12.1: Create module structure**

```
src/sqlseed/core/
├── orchestrator.py      # Orchestration entry (< 200 lines): __init__, from_config, fill_table (delegates), preview_table, context manager
├── _connection.py       # ConnectionManager: _create_adapter, _ensure_connected, close, __enter__, __exit__
├── _spec_resolver.py    # SpecResolver: _resolve_specs, _prepare_specs, _build_stream, _resolve_user_configs
├── _batch_writer.py     # BatchWriter: _generate_and_insert_batches, fill_table logic (prepare→generate→finalize)
└── _query.py            # QueryExecutor: execute, query, fetch_one, get_row_count, get_column_info, etc.
```

- [ ] **Step 12.2: Implement `_connection.py`**

Move connection lifecycle methods:
- `_create_adapter` (line 187)
- `_ensure_connected` (line 199)
- `close` (line 751)
- `__enter__` (line 756)
- `__exit__` (line 760)
- Properties: `_db`, `_schema`, `_mapper`, `_relation`, `_shared_pool`

- [ ] **Step 12.3: Implement `_spec_resolver.py`**

Move spec preparation methods:
- `_resolve_specs` (line 221)
- `_prepare_specs` (line 286)
- `_build_stream` (line 256)
- `_resolve_user_configs` (line 664)

- [ ] **Step 12.4: Implement `_batch_writer.py`**

Move batch generation methods:
- `_generate_and_insert_batches` (line 364)
- `fill_table` logic split into `_prepare` → `_generate` → `_finalize`

- [ ] **Step 12.5: Implement `_query.py`**

Move query methods:
- `execute` (line 703)
- `query` (line 718)
- `fetch_one` (line 733)
- `get_row_count` (line 646)
- `get_column_info` (line 638)
- `get_foreign_keys` (line 642)
- Other query-like methods

- [ ] **Step 12.6: Reduce `orchestrator.py` to < 200 lines**

Keep only:
- `__init__` (delegates to ConnectionManager)
- `from_config` classmethod
- `fill_table` (delegates to BatchWriter)
- `preview_table` (delegates to BatchWriter)
- `get_schema_context` (delegates)
- `report` (delegates)
- Context manager (delegates to ConnectionManager)

- [ ] **Step 12.7: Agent A self-check**

```powershell
cd c:\Users\14435\Desktop\sqlseed-worktree-a
ruff check .
mypy src plugins
python -c "from sqlseed import fill, connect, fill_from_config, preview; print('OK')"
python -c "from sqlseed.core.orchestrator import DataOrchestrator; print('OK')"
```
Expected: All checks pass, public API unchanged.

### Step 13: Agent B — Split by domain

**Working directory:** `c:\Users\14435\Desktop\sqlseed-worktree-b`

**Approach:** Split `orchestrator.py` (761 lines) by domain responsibility.

- [ ] **Step 13.1: Create module structure**

```
src/sqlseed/core/
├── orchestrator.py      # Orchestration entry (< 200 lines): __init__, from_config, fill_table (delegates), preview_table, context manager
├── _schema_handler.py   # Schema handling: _resolve_specs, _prepare_specs, get_schema_context, get_column_info, get_column_names, get_skippable_columns, map_column, get_column_mapping
├── _data_generator.py   # Data generation: _build_stream, _generate_and_insert_batches, fill_table core logic
├── _plugin_coord.py     # Plugin coordination: _plugins, _plugin_mediator, _enrichment, _unique_adjuster, hook triggers
└── _relation_handler.py # Relation handling: _relation, get_foreign_keys, get_topological_table_order, register_shared_pool
```

- [ ] **Step 13.2: Implement `_schema_handler.py`**

Move schema-related methods:
- `_resolve_specs` (line 221)
- `_prepare_specs` (line 286)
- `get_schema_context` (line 574)
- `get_column_info` (line 638)
- `get_column_names` (line 618)
- `get_skippable_columns` (line 622)
- `map_column` (line 650)
- `get_column_mapping` (line 687)

- [ ] **Step 13.3: Implement `_data_generator.py`**

Move data generation methods:
- `_build_stream` (line 256)
- `_generate_and_insert_batches` (line 364)
- `fill_table` core logic (prepare → generate → finalize)
- `preview_table` (line 546)

- [ ] **Step 13.4: Implement `_plugin_coord.py`**

Move plugin coordination:
- Plugin/enrichment/adjuster properties
- Hook trigger calls
- `_resolve_user_configs` (line 664)

- [ ] **Step 13.5: Implement `_relation_handler.py`**

Move relation handling:
- `get_foreign_keys` (line 642)
- `get_topological_table_order` (line 630)
- `register_shared_pool` calls
- `get_table_names` (line 634)

- [ ] **Step 13.6: Reduce `orchestrator.py` to < 200 lines**

Keep only orchestration entry points, delegating to domain handlers.

- [ ] **Step 13.7: Agent B self-check**

```powershell
cd c:\Users\14435\Desktop\sqlseed-worktree-b
ruff check .
mypy src plugins
python -c "from sqlseed import fill, connect, fill_from_config, preview; print('OK')"
python -c "from sqlseed.core.orchestrator import DataOrchestrator; print('OK')"
```
Expected: All checks pass, public API unchanged.

### Step 14: Agent C — Fusion

- [ ] **Step 14.1: Compare both implementations**

```powershell
git diff feat/multi-db-support-h1-agent-a -- src/sqlseed/core/
git diff feat/multi-db-support-h1-agent-b -- src/sqlseed/core/
```

- [ ] **Step 14.2: Evaluate and choose fusion strategy**

Assess:
- Agent A: 4 modules by lifecycle (connection, spec_resolver, batch_writer, query)
- Agent B: 4 modules by domain (schema_handler, data_generator, plugin_coord, relation_handler)

**Fusion decision criteria:**
- Which split has more cohesive modules (single responsibility)?
- Which split makes `fill_table` easier to understand?
- Which split has cleaner dependency graph (no circular imports)?
- Choose the better split, cherry-pick improvements from the other
- **Must:** `fill_table` split into `_prepare` → `_generate` → `_finalize` three phases
- **Must:** `orchestrator.py` < 200 lines

- [ ] **Step 14.3: Apply fused result**

Create the fused version in the main working directory.

- [ ] **Step 14.4: Stage 2 validation**

```powershell
cd c:\Users\14435\Desktop\sqlseed
ruff check .
mypy src plugins
python -m pytest tests/test_orchestrator.py --tb=short -q
python -c "from sqlseed import fill, connect, fill_from_config, preview; print('OK')"
python -c "from sqlseed.core.orchestrator import DataOrchestrator; print('OK')"
```
Expected: All checks pass.

### Step 15: Merge and final validation

- [ ] **Step 15.1: Commit fused result**

```powershell
git add src/sqlseed/core/
git commit -m "refactor: split DataOrchestrator into focused modules (H1) - 761 lines -> orchestrator < 200 lines + cohesive modules"
```

- [ ] **Step 15.2: Stage 3 validation**

```powershell
ruff check .
mypy src plugins
python -m pytest --tb=short -q
python -c "from sqlseed import fill, connect, fill_from_config, preview"
python -c "from sqlseed.core.orchestrator import DataOrchestrator"
python -c "from sqlseed.cli.main import cli; cli(['--help'])"
```
Expected: All checks pass, public API unchanged, CLI works.

- [ ] **Step 15.3: Clean up worktrees**

```powershell
git worktree remove ../sqlseed-worktree-a
git worktree remove ../sqlseed-worktree-b
git branch -D feat/multi-db-support-h1-agent-a feat/multi-db-support-h1-agent-b
git worktree list
```

### Step 16: Phase 1 final validation

- [ ] **Step 16.1: Full validation**

```powershell
ruff check .
ruff format --check .
mypy src plugins
python -m pytest --tb=short -q
python -c "from sqlseed import fill, connect, fill_from_config, preview"
python -c "from sqlseed_ai.analyzer import SchemaAnalyzer"
python -c "from sqlseed.cli.main import cli; cli(['--help'])"
git worktree list
```
Expected: All checks pass, no worktree residue.

- [ ] **Step 16.2: Verify orchestrator.py line count**

```powershell
# Count lines in orchestrator.py
(Get-Content src/sqlseed/core/orchestrator.py | Measure-Object -Line).Lines
```
Expected: < 200 lines

- [ ] **Step 16.3: Verify no circular imports**

```powershell
python -c "import sqlseed; import sqlseed.cli; import sqlseed.cli.ai_commands; print('No circular imports')"
```
Expected: No ImportError

---

## Self-Review Checklist

- [ ] H4: CLI circular dependency fixed, `sqlseed --help` works
- [ ] H3: analyzer.py split into package, `from sqlseed_ai.analyzer import SchemaAnalyzer` works
- [ ] H1: orchestrator.py < 200 lines, `from sqlseed import fill, connect` works
- [ ] All worktrees cleaned up (git worktree list shows only main)
- [ ] All temporary branches deleted
- [ ] ruff + mypy + pytest pass
- [ ] No public API changes
