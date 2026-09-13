# sqlseed Project Comprehensive Consolidation Design Document

**Date**: 2026-06-20
**Status**: Pending Review
**Scope**: Comprehensive consolidation (P0 dead code cleanup → P1 dependency and architecture consolidation → P2 plugin boundary clarification → P3 deep consolidation)

---

## 1. Consolidation Principles

| Principle | Meaning |
|-----------|---------|
| **Core = Minimal changes** | Data generation engine, mapping rules, configuration models — minor maintenance going forward |
| **Plugins = Major changes** | AI, MCP, domain templates — extend via plugins |
| **Correct format > Correct semantics** | init-generated templates must have correct format; business meaning is user-adjustable |
| **Core code unchanged going forward** | After consolidation, core logic is stable and no longer adjusted |
| **Stay within boundaries** | Core only does core things; does not overstep into business logic |
| **Each cleanup must be tested** | Run pytest after cleanup to confirm no impact |

## 2. Core Architecture Boundaries

```
sqlseed core (minimal changes, no major refactoring after consolidation):
├── Data generation engine
│   ├── mapper.py — 9-level column mapping (74 exact + 27 regex)
│   ├── schema.py — Schema inference
│   ├── constraints.py — UNIQUE constraint solving
│   ├── column_dag.py — DAG column dependency ordering
│   ├── expression.py — Expression engine (simpleeval)
│   └── orchestrator.py — Orchestrator
├── Database adapter layer
│   ├── SQLAlchemyAdapter — required core dependency (unified adapter for SQLite/PG/MySQL)
│   ├── RawSQLiteAdapter — test-only (Python built-in sqlite3, zero extra dependencies)
│   └── _dialect.py — Dialect abstraction
├── Data providers
│   ├── faker — required dependency (standard coverage + consistency profiles)
│   ├── mimesis — optional dependency (high-performance batch)
│   └── base — type routing layer (does not generate real data)
├── Plugin system
│   └── pluggy hooks (11)
├── Configuration models
│   └── Pydantic models + YAML/JSON loader
└── Access methods
    ├── Python API (fill, connect, preview, fill_from_config)
    └── CLI (fill, preview, inspect, init, replay)

sqlseed plugins (major changes/optional):
├── sqlseed-ai — AI schema analysis (Gemma 4)
├── mcp-server-sqlseed — MCP service
└── Future plugins (domain templates, etc.)
```

## 3. Phase 1: P0 Dead Code Cleanup

> Risk: Low. Run `pytest` after each cleanup to confirm no regression.

### 3.1 Delete SQLiteUtilsAdapter Ghost References

**Current state**: The `SQLiteUtilsAdapter` class no longer exists, but there are still 2 references:

| File | Line | Reference Content |
|------|------|-------------------|
| `src/sqlseed/database/sqlalchemy_adapter.py` | 370 | `# Returns 0 when table does not exist (consistent with SQLiteUtilsAdapter behavior)` |
| `src/sqlseed/database/_protocol.py` | 40 | `Existing RawSQLiteAdapter/SQLiteUtilsAdapter has not yet implemented these two properties` |

**Actions**:
- `sqlalchemy_adapter.py:370` — Remove the `SQLiteUtilsAdapter` reference in the comment, change to `consistent with RawSQLiteAdapter behavior`
- `_protocol.py:40` — Remove the `SQLiteUtilsAdapter` reference, change to `Existing RawSQLiteAdapter has not yet implemented these two properties`

**Validation**: `grep -r "SQLiteUtilsAdapter" src/` returns zero results + `pytest`

### 3.2 Delete create_batch_inserter Dead Code

**Current state**: In `_dialect.py`, the `Dialect` Protocol and both implementation classes define `create_batch_inserter`, but:
- `SQLiteDialect.create_batch_inserter` → `raise NotImplementedError`
- `PostgresDialect.create_batch_inserter` → `raise NotImplementedError`
- Actual batch writing is done by `SQLAlchemyBatchInserter` directly used in `SQLAlchemyAdapter.batch_insert()`
- The `BatchInserter` Protocol and `create_batch_inserter` are never called

**Actions**:
1. Remove the `create_batch_inserter` method from the `Dialect` Protocol
2. Remove the `create_batch_inserter` method from `SQLiteDialect`
3. Remove the `create_batch_inserter` method from `PostgresDialect`
4. Remove the `BatchInserter` Protocol class
5. Remove `"BatchInserter"` from `__all__`
6. Remove `BatchInserter` import and export from `database/__init__.py`

**Validation**: `grep -r "create_batch_inserter\|BatchInserter" src/` returns zero results + `pytest`

### 3.3 Delete orchestrator.py Unused Public API

**Current state**: `DataOrchestrator` has 4 public methods that are never called externally within core code:

| Method | Line | Description |
|--------|------|-------------|
| `execute()` | 604 | Delegates to `self._db.execute()` |
| `query()` | 619 | SELECT wrapper based on execute |
| `fetch_one()` | 634 | Single-row query based on execute |
| `fetch_all()` | 652 | Multi-row query based on execute |

**Analysis**:
- `execute()` is called internally by `query()`/`fetch_one()`/`fetch_all()`
- `execute()` is exported as public API in `__init__.py` (the `fill()` function does not use it)
- These 4 methods have zero external calls within `src/` (grep confirms `orchestrator.fetch_one|fetch_all|query|execute` has no matches)
- But `execute()` may have external user dependencies (as public API)

**Actions**:
- Keep `execute()` — it is part of the public API; users may call it directly
- Keep `query()` — returns `list[dict]`, auto-converts tuple→dict, provides excellent script validation experience
- Keep `fetch_one()` — returns `dict | None`, convenient wrapper for single-row queries
- Delete `fetch_all()` — returns `list[Any]` (raw tuple list), completely equivalent to `execute()` + cursor.fetchall(), redundant
- Remove `fetch_all` from `__all__` in `__init__.py` (if present)

**Validation**: `pytest` + confirm `execute()`/`query()`/`fetch_one()` still work

## 4. Phase 2: P1 Dependency and Architecture Consolidation

> Risk: Medium. Run `pytest` + `mypy` after each change to confirm no regression.

### 4.1 Promote faker to Required Dependency

**Current state**: faker is an optional dependency (`pip install sqlseed[faker]`), base_provider contains 370 hardcoded data items as fallback.

**Actions**:
1. In `pyproject.toml`, move `faker` from `[project.optional-dependencies]` to `[project.dependencies]`
2. Remove `faker` from the `"all"` list in `[project.optional-dependencies]`
3. Update dependency descriptions in `AGENTS.md` / `CLAUDE.md`

**Rationale**:
- faker is the most mature Python fake data library with excellent Chinese support
- As a required dependency, base_provider's hardcoded data can be removed
- Fallback chain: mimesis (optional high-performance) → faker (required standard) → base (type routing only)

**Validation**: `pip install -e .` auto-installs faker + `pytest`

### 4.2 base_provider Refactoring

**Current state**: `base_provider.py` is 684 lines, containing ~370 hardcoded data items (Chinese surnames, cities, email domains, etc.).

**Actions**:
1. Remove all hardcoded data lists (`_LAST_NAMES_ZH`, `_CITIES_ZH`, etc.)
2. Change `_gen_*` methods to generate synthetic placeholder data, e.g.:
   - `name` → `"user_001"`, `"user_002"`, ...
   - `email` → `"user_001@placeholder.com"`, ...
   - `address` → `"addr_001"`, ...
   - `phone` → `"000-0000-0001"`, ...
   - `city` → `"city_001"`, ...
3. Keep the type routing logic (`GENERATOR_MAP` dispatch)
4. Keep the `generate()` method signature unchanged

**Design Principles**:
- base provider guarantees **correct format** (email has @, phone has dashes), not **realistic semantics**
- When faker is available, faker is automatically used to generate real data
- Without faker (theoretically won't happen since faker is a required dependency), degrades to placeholder data

**Validation**: `pytest` + manual verification `pip install -e . --no-deps && python -c "from sqlseed.generators.base_provider import BaseProvider; p = BaseProvider(); print(p.generate('name'))"` outputs placeholder data

### 4.3 Keep SQLAlchemy as Required Core Dependency

**Current state**: SQLAlchemy is already a required core dependency (`pyproject.toml` line 39 `"sqlalchemy>=2.0"`), `DataOrchestrator._create_adapter()` unconditionally returns `SQLAlchemyAdapter()`.

**Actions**:
1. Confirm SQLAlchemy remains a required core dependency, no downgrade
2. Keep `RawSQLiteAdapter` but only for testing (not part of production code path)
3. Update descriptions in `AGENTS.md` / `CLAUDE.md` to clarify SQLAlchemy is a core dependency

**Rationale**:
- The code is already implemented this way (`_create_adapter()` unconditionally uses SQLAlchemyAdapter)
- Multi-DB support is a core capability; SQLAlchemy is its foundation
- Keeping it required avoids the complexity of downgrade logic (if made optional, would need to write auto-downgrade in orchestrator: detect no SQLAlchemy + SQLite file → switch to RawSQLiteAdapter, increasing maintenance cost)
- SQLAlchemy is a mature, stable library; as a required dependency it does not burden users

**Validation**: `pytest` + confirm `pip install -e .` auto-installs SQLAlchemy

## 5. Phase 3: P2 Plugin Boundary Clarification

> Risk: Low to medium. Run `pytest` + `ruff` + `mypy` after each change.

### 5.1 CLI Circular Dependency Status Confirmation

**Current state**: `main.py` registers AI commands at module level via `try: import sqlseed.cli.ai_commands`, and `ai_commands.py` obtains the CLI group via `from sqlseed.cli.main import cli`. Currently avoids circular ImportError through load order (define `cli` first, then import `ai_commands`).

**Analysis**:
- The current `try: import` + load order pattern is already a reasonable solution
- Lazy imports (importing inside command functions) are not feasible — Click command registration happens at load time, lazy imports would prevent Click from discovering the `ai-suggest` command
- `ai_commands.py` uses `@cli.command()` decorator to register commands, must be imported after `cli` is defined
- `try: import` already handles the case where `sqlseed-ai` is not installed (ImportError → pass)

**Actions**:
- Keep as-is, no modifications
- Add comments in `main.py` explaining the current design decision and circular dependency avoidance strategy
- Add comments in `ai_commands.py` explaining the import order dependency

**Validation**: `pytest tests/test_cli.py` + `python -c "from sqlseed.cli.main import cli"`

### 5.2 Unify tqdm and rich.progress

**Current state**: `progress.py` uses both `rich.progress` (terminal) and `tqdm.auto` (Jupyter); tqdm is an optional dependency.

**Actions**:
- Keep the current dual-backend design (tqdm for Jupyter environments, rich for terminals)
- Move tqdm from `[project.optional-dependencies]` to the `"notebook"` group in `[project.optional-dependencies]`
- Do not remove tqdm support, as tqdm is the best choice in Jupyter environments

**Rationale**:
- tqdm has native widget support in Jupyter; rich does not
- The two serve different environments; they are not redundant
- Keep tqdm optional; Jupyter users install on demand

**Validation**: `pytest` + verify terminal progress bar works without tqdm

### 5.3 Documentation Sync

**Current state**: `docs/architecture.md` is not synced with 5 new database/ files (`_dialect.py`, `_type_normalizer.py`, `_bulk_optimizer.py`, `_base_adapter.py`, `_helpers.py`).

**Actions**:
1. Update the file list and descriptions for the database module in `docs/architecture.md`
2. Update corresponding content in `docs/architecture.zh-CN.md`
3. Run `pytest tests/test_doc_sync.py` to validate

**Validation**: `pytest tests/test_doc_sync.py`

## 6. Phase 4: P3 Deep Consolidation (Optional)

> Risk: Medium. Requires more design and testing.

### 6.1 Provider Three-Layer Refactoring

**Current state**: The fallback logic for the three-layer Provider (mimesis → faker → base) is scattered in `_ensure_connected()`.

**Actions**:
- Unify the Provider interface, simplify the fallback chain
- Centralize the fallback logic in a `ProviderRegistry` class
- Each layer's Provider only implements the `generate()` method

**Note**: This phase requires more detailed design; recommend evaluating after P0-P2 are complete.

### 6.2 analyzer.py Split

**Current state**: `plugins/sqlseed-ai/src/sqlseed_ai/analyzer.py` is large.

**Actions**:
- Split by responsibility: prompt construction, LLM calls, result parsing, streaming processing

**Note**: This phase is internal plugin refactoring; priority is lower than core consolidation.

## 7. Validation Strategy

After each phase, execute:

```bash
# 1. Code quality
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/

# 2. Full test suite
pytest

# 3. Documentation sync
pytest tests/test_doc_sync.py

# 4. Installation validation
pip install -e ".[dev,all]"
```

## 8. Risks and Rollback

| Risk | Impact | Rollback Plan |
|------|--------|---------------|
| External users break after `fetch_all` removal | Very low | `fetch_all()` returns raw tuple list, equivalent to `execute()` + cursor.fetchall(); users can easily substitute |
| faker as required dependency increases install size | Low | faker ~3MB, acceptable for most users |
| base_provider refactoring produces unrealistic data without faker | Very low | faker is a required dependency; this scenario won't occur |
| `create_batch_inserter` removal affects future PG COPY optimization | Low | `SQLAlchemyBatchInserter` is already implemented; future COPY optimization happens at the adapter layer |

## 9. Out of Consolidation Scope

| Item | Reason |
|------|--------|
| 9-level column mapping rule extension | Core guarantees correct format; business semantics handled by user/AI/plugins |
| New domain templates | Plugin extension; not in core consolidation scope |
| AI plugin feature enhancements | Plugin; nice-to-have but keep as-is |
| RawSQLiteAdapter removal | Kept as zero-dependency test foundation |
| SQLAlchemy downgrade to optional dependency | Code already unconditionally uses SQLAlchemyAdapter; downgrade would require auto-downgrade logic, violating the "core code unchanged going forward" principle |

---

## Appendix: Review Revision Records

### Revision 1: SQLAlchemy Dependency Positioning

**Original design**: SQLAlchemyAdapter as optional dependency
**Revised to**: SQLAlchemy remains a required core dependency

**Reason**:
- `pyproject.toml` already has `sqlalchemy>=2.0` in `[project.dependencies]`
- `DataOrchestrator._create_adapter()` unconditionally returns `SQLAlchemyAdapter()`
- Comments explicitly state `Phase 4: Unified use of SQLAlchemyAdapter (SQLAlchemy is already a core dependency)`
- Downgrading to optional would require writing auto-downgrade logic in orchestrator (no SQLAlchemy + SQLite → RawSQLiteAdapter), increasing core code complexity, violating the "core code unchanged going forward" principle

### Revision 2: CLI Circular Dependency Handling

**Original design**: Change `ai_commands` to lazy import
**Revised to**: Keep as-is, add comments

**Reason**:
- The actual code is `try: import sqlseed.cli.ai_commands` (module-level import triggers decorator registration), not `from ... import ai_suggest`
- Click command registration happens at load time; lazy imports would make `ai-suggest` undiscoverable
- The current `try: import` + load order pattern already reasonably handles both circular dependency and sqlseed-ai not installed cases

### Revision 3: orchestrator Query Method Retention Strategy

**Original design**: Delete query/fetch_one/fetch_all, keep only execute()
**Revised to**: Keep query() and fetch_one(), delete only fetch_all()

**Reason**:
- `query()` returns `list[dict]`, auto-converts tuple→dict, provides excellent script validation experience
- `fetch_one()` returns `dict | None`, convenient wrapper for single-row queries
- `fetch_all()` returns `list[Any]` (raw tuple list), completely equivalent to `execute()` + cursor.fetchall(), is the only truly redundant method
