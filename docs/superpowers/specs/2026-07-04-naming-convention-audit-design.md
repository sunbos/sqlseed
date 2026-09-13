# Naming Convention Audit Design

**Date:** 2026-07-04
**Status:** Approved (pending user review)
**Scope:** `src/sqlseed/` + `plugins/*/src/` source code, plus documentation alignment

## 1. Overview

### 1.1 Goal

Audit naming conventions across `src/sqlseed/` and `plugins/` source code against PEP 8, project conventions, and best practices. Produce a structured report of all naming issues, then fix them in priority-ordered batches after per-item user confirmation. Final state: all issues resolved, CI green, documentation aligned.

### 1.2 Constraints (from user)

- **Audit dimensions**: Five code categories — spelling/grammar (S), PEP 8 conformance (P), consistency/readability (C), file/module organization (F), project conventions (PC) — plus documentation alignment (D) for code-vs-doc granularity checks.
- **Modification cadence**: Report first, per-item confirmation, then fix. Final goal: resolve all issues.
- **Backward compatibility**: Not required. Optimize for best practices and long-term stability.
- **CI compliance**: `.github/workflows/ci.yml` MUST pass after all modifications.
- **Documentation alignment**: Code may be out of sync with markdown docs. Audit must verify code-vs-doc granularity alignment (not just identifier existence).

### 1.3 Non-Goals

- Test file naming audit (test convention already enforced: `test_<module>.py`, `Test<Feature>` classes).
- Configuration files (`pyproject.toml`, `scripts/`).
- Documentation prose style (only identifier/code alignment is audited).
- Architectural refactoring beyond renaming.

## 2. Audit Scope

### 2.1 Source Code (full audit)

```
c:\Users\14435\Desktop\sqlseed\src\sqlseed\                    (core package)
c:\Users\14435\Desktop\sqlseed\plugins\sqlseed-ai\src\         (AI plugin)
c:\Users\14435\Desktop\sqlseed\plugins\sqlseed-cli\src\        (CLI plugin)
c:\Users\14435\Desktop\sqlseed\plugins\mcp-server-sqlseed\src\ (MCP plugin)
```

### 2.2 Documentation (alignment audit only)

```
c:\Users\14435\Desktop\sqlseed\AGENTS.md
c:\Users\14435\Desktop\sqlseed\CLAUDE.md
c:\Users\14435\Desktop\sqlseed\GEMINI.md
c:\Users\14435\Desktop\sqlseed\README.md
c:\Users\14435\Desktop\sqlseed\README.zh-CN.md
c:\Users\14435\Desktop\sqlseed\ARCHITECTURE.md
c:\Users\14435\Desktop\sqlseed\ARCHITECTURE.zh-CN.md
c:\Users\14435\Desktop\sqlseed\CONTRIBUTING.md
c:\Users\14435\Desktop\sqlseed\CHANGELOG.md
c:\Users\14435\Desktop\sqlseed\CHANGELOG.zh-CN.md
c:\Users\14435\Desktop\sqlseed\docs\**\*.md
c:\Users\14435\Desktop\sqlseed\src\sqlseed\**\AGENTS.md
c:\Users\14435\Desktop\sqlseed\plugins\**\AGENTS.md
c:\Users\14435\Desktop\sqlseed\plugins\**\README*.md
```

## 3. Audit Checklist (32 items)

### 3.1 Dimension S — Spelling & Grammar

| ID | Check | Example |
|----|-------|---------|
| S1 | Identifier spelling errors | `bakend` → `backend` |
| S2 | Inconsistent spelling of same concept | `db` / `database` / `db_path` mixed |
| S3 | Spelling errors in comments/docstrings | — |

### 3.2 Dimension P — PEP 8 Conformance

| ID | Check | Example |
|----|-------|---------|
| P1 | Module names: snake_case, `_` prefix for private | `_dispatch.py` OK |
| P2 | Package names: short snake_case | `sqlseed_ai` OK |
| P3 | Class names: PascalCase | `DataOrchestrator` OK |
| P4 | Function/method/variable: snake_case | — |
| P5 | Constants: UPPER_CASE | `GENERATOR_MAP` OK |
| P6 | Type aliases: PascalCase (PEP 561) | `DataProvider` OK |
| P7 | Private members: `_` prefix (single underscore) | `_seen` OK |
| P8 | Name mangling (`__` double underscore) only when necessary | — |

### 3.3 Dimension C — Consistency & Readability

| ID | Check | Example |
|----|-------|---------|
| C1 | Same concept named consistently across files | `db_path` vs `database_path` |
| C2 | Abbreviations used consistently | `url` vs `uri` / `cfg` vs `config` |
| C3 | Function names start with verb | `get_xxx`, `build_xxx`, `apply_xxx` |
| C4 | Boolean variables/attributes use `is_`/`has_`/`should_` prefix | `is_primary_key` OK |
| C5 | Parameter names intuitive, unambiguous | avoid `data1, data2` |
| C6 | Avoid single-letter variables (except loop counters `i, j, k`) | — |
| C7 | Avoid Hungarian notation (type prefixes) | `str_name`, `int_count` BAD |

### 3.4 Dimension F — File & Module Organization

| ID | Check | Example |
|----|-------|---------|
| F1 | Module name reflects responsibility | `stream.py` (data stream) OK |
| F2 | Private modules use `_` prefix (package-internal only) | `_helpers.py` OK |
| F3 | Single responsibility: one module, one main concern | avoid grab-bag |
| F4 | Avoid name collisions (same-named private modules across packages) | multiple `_protocol.py` need evaluation |

### 3.5 Dimension PC — Project Conventions

| ID | Check | Example |
|----|-------|---------|
| PC1 | Test files: `test_<module>.py` | `test_stream.py` OK |
| PC2 | Test classes: `Test<Feature>`, test functions: `test_<scenario>` | OK |
| PC3 | `from __future__ import annotations` at file top | OK |
| PC4 | Logger naming: `logger = get_logger(__name__)` | OK |

### 3.6 Dimension D — Documentation Alignment

| ID | Check | Example |
|----|-------|---------|
| D1 | Documented module paths still exist | `src/sqlseed/core/mapper.py` exists |
| D2 | Documented class/function names match code | `ColumnMapper` unchanged |
| D3 | Documented field/enum values match code | `tool_calling_protocol: Literal["gemma4", "openai", "none"]` |
| D4 | Count markers in docs match code | exact match rule count = 75 |
| D5 | Documented API signatures match code | function params/types/defaults |
| D6 | Code examples in docs are runnable | README examples execute |
| D7 | Documented rule numbers/behaviors match code | Rule #14 description vs `_apply_rule_14_strip_invalid_params` |
| D8 | Documented architecture matches code | "4 independent packages" vs actual structure |
| D9 | Documented field types/constraints match code | `max_tokens: int = Field(ge=0)` |
| D10 | Documented class diagrams match code | dataclass fields, inheritance |

## 4. Scan Strategy (4 layers)

### 4.1 Layer 1 — Automated Tool Scan (baseline)

```bash
ruff check src/ plugins/ --select=N    # pep8-naming rules
ruff check src/ plugins/ --select=F    # pyflakes unused variables
codespell src/ plugins/ docs/          # systematic spell-check (S1/S3 coverage)
```

`codespell` scans comments, docstrings, and markdown prose for common misspellings that regex grep might miss (e.g., `recieve`, `seperate`, `occured`, `sucess`, `bakend`). Catches both code identifiers (S1) and comment/docstring typos (S3). If `codespell` is not installed, install via `pip install codespell`. Configure ignore-words in `pyproject.toml` `[tool.codespell]` if false positives arise.

### 4.2 Layer 2 — Pattern Grep Scan (semantic issues)

Targeted grep per checklist dimension. Examples:

- **Spelling candidates**: `grep -i "bakend|recieve|seperate|occured|sucess"`
- **Inconsistent abbreviations**: `grep -E "\bdb\b|\bdf\b|\bcfg\b|\bidx\b|\bnum\b"`
- **Same concept, multiple spellings**: `database_path` vs `db_path` vs `database`
- **Single-letter variables**: `grep -E "\b[xyz]\b\s*="` (except `i/j/k`)
- **Hungarian notation**: `grep -E "\b(str_|int_|bool_|list_|dict_)[a-z]+"`
- **Boolean without `is_/has_` prefix**: `grep -E "^\s+\w+:\s*bool\s*="`

### 4.3 Layer 3 — Manual Read Spot-Check (structural/semantic depth)

- Read each package's `__init__.py` to audit public API naming.
- Read core modules (`stream.py`, `constraints.py`, `mapper.py`, `orchestrator/`) one by one.
- Check: module single-responsibility (F3), function verb-prefix (C3), parameter consistency (C1/C5), private/public boundary (P7).

### 4.4 Layer 4 — Documentation Alignment Scan

- Extract identifiers from markdown code blocks (```python ... ```) and backtick-quoted identifiers.
- Reverse-verify: every documented identifier exists in code with matching spelling.
- Key comparisons:
  - CLAUDE.md "Plugin Hooks (12 total)" table vs `hookspecs.py` actual hook count.
  - CLAUDE.md "Public API" table vs `__init__.py` actual exports.
  - CLAUDE.md count markers vs code actual counts.
  - README example code vs actual API signatures.
  - AGENTS.md file paths vs actual file structure.
  - ARCHITECTURE.md class diagrams vs actual dataclass fields.

## 5. Output Format

### 5.1 Report File

`docs/superpowers/specs/2026-07-04-naming-convention-audit-report.md`

### 5.2 Structured Entry Format

Each finding is one entry:

```markdown
### NNN | <dimension-id> | <priority> | <file:line>

**Problem**: <one-sentence description>
**Current**:
\`\`\`python
<code snippet>
\`\`\`
**Suggestion**: <fix suggestion>
**Rationale**: <best practice / PEP / project convention>
**Impact**: <number of call sites affected>
```

### 5.3 Entry Example

```markdown
### 001 | S1 | P0 | plugins/sqlseed-ai/src/sqlseed_ai/_model_selector.py:125

**Problem**: Variable name `bakend` is misspelled.
**Current**:
\`\`\`python
to_model=next_model.to_backend_id(backend) if bakend else next_model.value,
\`\`\`
**Suggestion**: Rename to `backend`.
**Rationale**: Spelling error (S1); was silently masked by structlog no-op at WARNING level.
**Impact**: 1 call site (already fixed, shown as example).
```

### 5.4 Report Organization

Grouped by dimension, sorted by priority descending within each group:

```
## 1. Spelling & Grammar (S)
### 001 | S1 | P0 | ...
### 002 | S2 | P1 | ...

## 2. PEP 8 Conformance (P)
### 010 | P3 | P2 | ...

## 3. Consistency & Readability (C)
...

## 4. File & Module Organization (F)
...

## 5. Project Conventions (PC)
...

## 6. Documentation Alignment (D)
...

## Summary Statistics
| Dimension | P0 | P1 | P2 | P3 | Subtotal |
|-----------|----|----|----|----|----------|
| S Spelling | 1 | 2 | 0 | 0 | 3 |
| P PEP8     | 0 | 1 | 5 | 2 | 8 |
| ...        |    |    |    |    |          |
| Total      | 1  | 5  | 12 | 3  | 21       |
```

### 5.5 Priority Levels

- **P0 (Critical)**: Spelling errors, obvious bugs (e.g., `bakend`).
- **P1 (High)**: Cross-file inconsistency, misleading names, docs reference non-existent identifiers.
- **P2 (Medium)**: PEP 8 violations, readability issues.
- **P3 (Low)**: Style polish, minor redundancy.

## 6. Workflow (4 stages)

### 6.1 Stage 1 — Scan & Collect (no code modification)

- Execute all 4 scan layers.
- Collect all findings, deduplicate.
- Generate structured report draft.

### 6.2 Stage 2 — User Per-Item Confirmation

User reviews report, marks each entry:
- `✓` Agree to fix
- `✗` Disagree (keep current)
- `?` Needs discussion

For `?` items, drill-down conversation.

### 6.3 Stage 3 — Batched Implementation (P0 → P1 → P2 → P3)

#### 6.3.1 Refactoring Tool Requirement (AST-aware, no regex global replace)

**MUST use AST-aware or LSP-aware refactoring tools** for all renames. Pure regex find-and-replace is **forbidden** because it risks collateral damage to log strings, unrelated same-name locals, and string literals.

Allowed tools (in priority order):
1. **IDE "Rename Symbol"** (Trae/VS Code/PyCharm) — LSP-based, scope-aware.
2. **`rope`** Python library — AST-based programmatic refactor.
3. **`pyrefly` / `pyright` rename** — type-aware rename.

If a rename must be done via `sed`/`Edit` (e.g., file rename), MUST manually verify each call site with `grep -rn "<old_name>"` before and after, and run the full test suite to confirm no collateral damage.

#### 6.3.2 Atomic Refactoring Commits (each commit is CI-green)

**Atomic principle**: Every commit MUST be independently CI-green. A rename and ALL its downstream effects (call sites, tests, documentation references, count markers) MUST land in the **same commit**.

**Forbidden pattern** (splits an atomic refactor across commits):
```
Commit A: rename `bakend` → `backend` in _model_selector.py  (CI red: test_doc_sync fails)
Commit B: update CLAUDE.md reference                          (CI green)
```

**Required pattern** (atomic):
```
Commit A: rename `bakend` → `backend` in _model_selector.py
          + update all call sites
          + update tests
          + update CLAUDE.md/AGENTS.md references
          + update count markers if any
          (CI green)
```

**Commit grouping strategy**:
- **Group by rename target**, not by dimension or priority.
- One commit per logical rename unit (identifier + all its references).
- If multiple independent renames belong to the same priority (e.g., 5 P0 spelling fixes), they MAY be batched into one commit ONLY if each rename is independently verifiable and they touch disjoint files.
- If a rename touches >20 files, still keep it as ONE commit (atomicity overrides size).
- Typical commit count: 10-30 commits total (one per rename unit), NOT 4 (one per priority).

**Commit message convention**:
```
refactor(naming): rename `bakend` → `backend` in _model_selector.py

- Fix typo in variable name (S1, P0)
- Update 3 call sites in analyzer/_caller.py
- Update CLAUDE.md reference in "AI backend fallback chain" section
- Update test_ai_model_selector.py assertions

Atomic refactor: definition + call sites + tests + docs in one commit.
```

#### 6.3.3 Cross-Package Synchronization (Monorepo coordination)

The sqlseed monorepo has 4 strongly-coupled packages. Renaming a public API in `src/sqlseed/` (core) immediately breaks dependent plugins. **All cross-package renames MUST be synchronized in the same commit.**

**Coupling matrix** (must sync in same commit):

| Core rename (src/sqlseed/) | Affected plugins (must update in same commit) |
|---------------------------|-----------------------------------------------|
| `__init__.py` public exports (`fill`, `connect`, `preview`, ...) | `sqlseed-cli`, `sqlseed-ai`, `mcp-server-sqlseed` |
| `plugins/hookspecs.py` hook names | All plugins implementing that hook |
| `generators/_protocol.py` `DataProvider` protocol | `sqlseed-cli` (if it type-hints providers) |
| `database/_protocol.py` `DatabaseAdapter` protocol | Plugin tests using adapters |
| `config/models.py` Pydantic field names | `sqlseed-cli` (CLI flags), `sqlseed-ai` (AIConfig), `mcp-server-sqlseed` (YAML gen) |
| `core/orchestrator/` public methods | `sqlseed-cli`, `mcp-server-sqlseed` (calls `fill_table`, `preview_table`) |

**Verification after each commit**:
```bash
# MUST all pass before committing
ruff check src/ tests/ plugins/
ruff format --check src/ tests/ plugins/
mypy
pytest tests/test_architecture.py -v
pytest tests/test_doc_sync.py -v
lint-imports
pytest --tb=short -q
```

**Forbidden**: committing a core rename without updating plugin call sites, even if "I'll fix the plugin in the next commit". The monorepo CI runs all packages together — any intermediate red state blocks merge.

**Platform compatibility constraints** (CI runs on macOS/Windows/Ubuntu):
- No new platform-specific code (no new `os.name == 'nt'` branches).
- Continue using `pathlib.Path` for paths (no hardcoded `/` or `\`).
- Preserve dialect abstraction (no SQLite-only syntax in generic paths).

### 6.4 Stage 4 — Final CI Full Validation

- Full lint + test suite.
- `pytest tests/integration/` if Docker available.
- Documentation sync: `pytest tests/test_doc_sync.py`.
- Pre-commit confirmation: `ruff check`, `ruff format --check`, `mypy`, `pytest` all green.

## 7. CI Validation Checklist (must pass before delivery)

- [ ] `ruff check src/ tests/ plugins/` passes
- [ ] `ruff format --check src/ tests/ plugins/` passes
- [ ] `mypy` passes
- [ ] `codespell src/ plugins/ docs/` passes (no new typos introduced)
- [ ] `pytest tests/test_architecture.py` passes
- [ ] `pytest tests/test_doc_sync.py` passes
- [ ] `lint-imports` passes
- [ ] `pytest --tb=short -q` full suite passes
- [ ] `pytest tests/integration/` passes (if Docker available)
- [ ] No new platform-specific code introduced
- [ ] All documentation references updated
- [ ] Each commit is independently CI-green (atomic refactoring)
- [ ] No regex-only renames performed (all renames used AST/LSP tools)

## 8. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Rename breaks `ruff check` | Run `ruff check src/ tests/ plugins/` after each commit |
| Rename breaks `ruff format --check` | Run `ruff format --check` after each commit |
| Rename breaks `mypy` strict | Run `mypy` after each commit |
| Rename breaks architecture guard | Run `pytest tests/test_architecture.py` after each commit |
| Rename breaks import-linter | Run `lint-imports` after each commit |
| Rename breaks cross-platform | Use `pathlib.Path`, no platform-specific code |
| Rename breaks PostgreSQL integration | Preserve dialect abstraction |
| Rename breaks doc count markers | Run `pytest tests/test_doc_sync.py` after each commit |
| Rename drops coverage | Check coverage report in Stage 4 |
| Documentation drift | Update all doc references in same commit as rename (atomic) |
| **Regex collateral damage** (log strings, same-name locals) | **6.3.1**: MUST use AST/LSP-aware tools, regex global replace forbidden |
| **Intermediate CI red state** (split atomic refactor) | **6.3.2**: Atomic commits — definition + call sites + tests + docs in one commit |
| **Cross-package breakage** (core rename breaks plugin) | **6.3.3**: Sync all plugin call sites in same commit as core rename |
| **Spell-check false positives** | Configure `[tool.codespell]` ignore-words in pyproject.toml |
| **Rename target count underestimated** | Stage 1 scan must be exhaustive; if new issues found during Stage 3, pause and re-confirm with user |

## 9. Success Criteria

1. All confirmed naming issues resolved.
2. CI checklist (Section 7) fully green.
3. Documentation aligned with code (D1-D10 all pass).
4. No regression in test coverage.
5. Each batch commit is traceable and revertable.
6. Final report updated to mark each entry as `✓ Fixed` or `✗ Kept (reason)`.

## 10. Deliverables

1. **Audit report**: `docs/superpowers/specs/2026-07-04-naming-convention-audit-report.md`
2. **Per-batch commits**: one commit per priority batch (P0, P1, P2, P3)
3. **Updated documentation**: all D-class issues resolved
4. **Final validation log**: output of all CI checklist commands

## 11. Out of Scope (explicit)

- Test file naming (already conventional).
- `pyproject.toml` / `scripts/` naming.
- Documentation prose style.
- Architectural refactoring beyond renaming.
- Performance optimization.
- New feature addition.
