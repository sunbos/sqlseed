# Naming Convention Audit — Stage 1: Scan & Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a structured audit report of all naming convention issues across `src/sqlseed/` and `plugins/` source code, plus documentation alignment issues, ready for user per-item confirmation.

**Architecture:** 4-layer scan (ruff + codespell + grep + manual read + doc reverse-verify) → deduplicate → structured Markdown report grouped by dimension (S/P/C/F/PC/D) with priority levels (P0-P3).

**Tech Stack:** ruff (pep8-naming), codespell, grep, pytest (for doc_sync verification), manual Read.

**Spec reference:** `docs/superpowers/specs/2026-07-04-naming-convention-audit-design.md`

---

## File Structure

**Create:**
- `docs/superpowers/specs/2026-07-04-naming-convention-audit-report.md` — the audit report (Stage 1 final deliverable)

**Read-only (audit targets):**
- `src/sqlseed/**/*.py` — core package source
- `plugins/sqlseed-ai/src/sqlseed_ai/**/*.py` — AI plugin source
- `plugins/sqlseed-cli/src/sqlseed_cli/**/*.py` — CLI plugin source
- `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/**/*.py` — MCP plugin source
- `*.md`, `docs/**/*.md`, `**/AGENTS.md` — documentation for alignment audit

**Modify:**
- `pyproject.toml` — add `[tool.codespell]` config if false positives arise (only if needed)

---

## Task 1: Install codespell and verify tooling

**Files:**
- Modify (if needed): `pyproject.toml` (add `[tool.codespell]` section)

- [ ] **Step 1: Install codespell**

Run:
```bash
pip install codespell
```

Expected: Successfully installed codespell.

- [ ] **Step 2: Verify ruff N-rules work**

Run:
```bash
ruff check src/ plugins/ --select=N --statistics
```

Expected: Output showing N-rule violation counts (or "All checks passed!" if no violations).

- [ ] **Step 3: Run codespell baseline scan**

Run:
```bash
codespell src/ plugins/ docs/
```

Expected: List of misspellings (if any). If false positives (e.g., project-specific terms), note them for Step 4.

- [ ] **Step 4: Configure codespell ignore-words (only if false positives found)**

If codespell reports false positives (e.g., "transportation" flagged as "transport"), add to `pyproject.toml`:

```toml
[tool.codespell]
ignore-words-list = "word1,word2"
```

If no false positives, skip this step.

- [ ] **Step 5: Commit codespell config (only if Step 4 ran)**

```bash
git add pyproject.toml
git commit -m "chore: add codespell config for naming audit"
```

If no config changes, skip this commit.

---

## Task 2: Run ruff N-rule scan and collect findings

**Files:**
- Read-only: `src/sqlseed/`, `plugins/*/src/`

- [ ] **Step 1: Run ruff N-rules with detailed output**

Run:
```bash
ruff check src/ plugins/ --select=N --output-format=concise > /tmp/ruff_n_findings.txt
```

Expected: File `/tmp/ruff_n_findings.txt` containing all pep8-naming violations with file:line:col.

- [ ] **Step 2: Read the findings file**

Run:
```bash
cat /tmp/ruff_n_findings.txt
```

Expected: List of violations like `src/sqlseed/core/mapper.py:128:1: N802 Function name should be lowercase`.

- [ ] **Step 3: Categorize each violation by checklist dimension**

For each violation, assign:
- Dimension (P1-P8 based on rule: N801=class/P3, N802=function/P4, N803=variable/P4, N806=variable in function/P4, N816=mixed-case variable/P4)
- Priority (P0 if spelling error, P2 if PEP 8 violation, P3 if style)
- File:line

Record findings in a temporary notes file `/tmp/audit_notes_layer1.md` under section "## Layer 1: ruff N-rules".

- [ ] **Step 4: Run ruff F-rules (unused variables)**

Run:
```bash
ruff check src/ plugins/ --select=F --output-format=concise > /tmp/ruff_f_findings.txt
```

Expected: List of unused variables/import violations.

- [ ] **Step 5: Categorize F-rule findings**

F-rule findings often indicate dead code or naming mismatches. Record in `/tmp/audit_notes_layer1.md` under "## Layer 1: ruff F-rules".

---

## Task 3: Run codespell scan and collect findings

**Files:**
- Read-only: `src/sqlseed/`, `plugins/`, `docs/`

- [ ] **Step 1: Run codespell with file/line output**

Run:
```bash
codespell src/ plugins/ docs/ > /tmp/codespell_findings.txt
```

Expected: File containing misspellings with format `path:line: col  wrong -> suggestion`.

- [ ] **Step 2: Read findings**

Run:
```bash
cat /tmp/codespell_findings.txt
```

Expected: List like `src/sqlseed/core/mapper.py:128: bakend -> backend`.

- [ ] **Step 3: Categorize each finding**

For each misspelling:
- If in code identifier (variable/function/class name) → S1, P0
- If in comment/docstring → S3, P3
- If in markdown doc → D2 (if identifier reference) or S3 (if prose)

Record in `/tmp/audit_notes_layer1.md` under "## Layer 1: codespell".

---

## Task 4: Pattern grep scan — Spelling (S1/S2/S3)

**Files:**
- Read-only: all `.py` files in `src/sqlseed/`, `plugins/*/src/`

- [ ] **Step 1: Grep for common misspellings in code**

Run:
```
Grep pattern: "bakend|recieve|seperate|occured|sucess|comparsion|lenght|widht|heigth|adress|refered|persistant|existant|definately|occassion|preceeding|proceedure|relevent|untill|wich|withing"
path: c:\Users\14435\Desktop\sqlseed\src\sqlseed
output_mode: content, -n: true, -i: true
```

Expected: List of any matches with file:line.

- [ ] **Step 2: Repeat grep for plugins**

Run:
```
Grep pattern: "bakend|recieve|seperate|occured|sucess|comparsion|lenght|widht|heigth|adress|refered|persistant|existant|definately|occassion|preceeding|proceedure|relevent|untill|wich|withing"
path: c:\Users\14435\Desktop\sqlseed\plugins
output_mode: content, -n: true, -i: true
```

- [ ] **Step 3: Grep for inconsistent concept spellings**

Run multiple greps:
```
Grep pattern: \bdb_path\b|\bdatabase_path\b|\bdatabase\b
path: c:\Users\14435\Desktop\sqlseed\src\sqlseed
output_mode: content, -n: true
```
```
Grep pattern: \burl\b|\buri\b
path: c:\Users\14435\Desktop\sqlseed\src\sqlseed
output_mode: content, -n: true
```

Record all S1/S2 findings in `/tmp/audit_notes_layer2.md` under "## S1/S2: Spelling & Inconsistency".

---

## Task 5: Pattern grep scan — Consistency (C1-C7)

**Files:**
- Read-only: all `.py` files

- [ ] **Step 1: Grep for inconsistent abbreviations**

Run:
```
Grep pattern: \bdb\b|\bdf\b|\bcfg\b|\bidx\b|\bnum\b|\battr\b|\bobj\b|\binfo\b|\bval\b
path: c:\Users\14435\Desktop\sqlseed\src\sqlseed
output_mode: content, -n: true
```

Record C2 findings (note: some abbreviations like `db` are acceptable if used consistently).

- [ ] **Step 2: Grep for Hungarian notation**

Run:
```
Grep pattern: \b(str_|int_|bool_|list_|dict_|float_|tuple_|set_)[a-z]+
path: c:\Users\14435\Desktop\sqlseed\src\sqlseed
output_mode: content, -n: true
```

Repeat for `plugins/`. Any matches → C7 violation, P2.

- [ ] **Step 3: Grep for boolean variables without is_/has_/should_ prefix**

Run:
```
Grep pattern: ^\s+\w+:\s*bool\s*=
path: c:\Users\14435\Desktop\sqlseed\src\sqlseed
output_mode: content, -n: true
```

For each match, check if the variable name starts with `is_`/`has_`/`should_`/`can_`/`_`. If not → C4 violation, P2.

- [ ] **Step 4: Grep for single-letter variables (non-loop counters)**

Run:
```
Grep pattern: \b[x-z]\b\s*=
path: c:\Users\14435\Desktop\sqlseed\src\sqlseed
output_mode: content, -n: true
```

Exclude `i/j/k` (acceptable loop counters). Each match → C6, P3.

- [ ] **Step 5: Record all C findings in `/tmp/audit_notes_layer2.md`**

---

## Task 6: Manual Read spot-check — core modules

**Files:**
- Read: `src/sqlseed/__init__.py`, `src/sqlseed/core/mapper.py`, `src/sqlseed/core/stream.py`, `src/sqlseed/core/constraints.py`, `src/sqlseed/core/orchestrator/__init__.py`, `src/sqlseed/generators/_dispatch.py`

- [ ] **Step 1: Read `src/sqlseed/__init__.py` and audit public API**

Read the file. Check:
- Public function names start with verbs (P4/C3): `fill`, `connect`, `preview`, `fill_from_config`, `load_config` — note any non-verb.
- Parameter names consistent (C1): `db_path` vs `url` mutually exclusive — note any inconsistency.
- Exports match CLAUDE.md "Public API" table (D5).

Record findings in `/tmp/audit_notes_layer3.md` under "## __init__.py public API".

- [ ] **Step 2: Read `src/sqlseed/core/mapper.py` and audit**

Read the file (focus on class/function definitions and key methods). Check:
- Class name PascalCase (P3): `ColumnMapper`.
- Method names snake_case + verb prefix (P4/C3): `map_column`, `_resolve_*`.
- Private methods use `_` prefix (P7).
- Module single-responsibility (F3): column mapping only.

Record findings.

- [ ] **Step 3: Read `src/sqlseed/core/stream.py` and audit**

Check: class/function naming, parameter consistency (e.g., `exclude_values` consistent across methods), private/public boundary.

- [ ] **Step 4: Read `src/sqlseed/core/constraints.py` and audit**

Check: `ConstraintSolver` class, `get_seen`/`try_register`/`check_and_register` verb prefixes, `_seen`/`_composite_seen` private fields.

- [ ] **Step 5: Read `src/sqlseed/core/orchestrator/__init__.py` and audit**

Check: `DataOrchestrator` class, mixin composition, public method names.

- [ ] **Step 6: Read `src/sqlseed/generators/_dispatch.py` and audit**

Check: `GeneratorDispatchMixin`, `GENERATOR_MAP` constant (UPPER_CASE P5), method names.

- [ ] **Step 7: Record all findings in `/tmp/audit_notes_layer3.md`**

---

## Task 7: Manual Read spot-check — plugin packages

**Files:**
- Read: `plugins/sqlseed-ai/src/sqlseed_ai/__init__.py`, `plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py`, `plugins/sqlseed-ai/src/sqlseed_ai/refiner.py`, `plugins/sqlseed-cli/src/sqlseed_cli/main.py`, `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/server.py`

- [ ] **Step 1: Read AI plugin `__init__.py` and audit**

- [ ] **Step 2: Read `staged_analyzer.py` (first 300 lines) and audit**

Check: `StagedSchemaAnalyzer`, `Stage3Validator`, `ErrorClassifier` class names; method verb prefixes.

- [ ] **Step 3: Read `refiner.py` (first 300 lines) and audit**

Check: `AiConfigRefiner` class, rule application methods like `_apply_rule_14_*`.

- [ ] **Step 4: Read CLI `main.py` (first 200 lines) and audit**

Check: Click command names (`fill`, `preview`, `inspect`), function naming.

- [ ] **Step 5: Read MCP `server.py` (first 200 lines) and audit**

Check: tool names (`sqlseed_generate_yaml`, `sqlseed_execute_fill`), function naming.

- [ ] **Step 6: Record all findings in `/tmp/audit_notes_layer3.md`**

---

## Task 8: Documentation alignment scan — D1-D4 (identifier existence)

**Files:**
- Read: `AGENTS.md`, `CLAUDE.md`, `README.md`, `ARCHITECTURE.md`, all `**/AGENTS.md`

- [ ] **Step 1: Extract module paths from CLAUDE.md and verify existence**

Read `CLAUDE.md`. For each path mentioned (e.g., `src/sqlseed/core/mapper.py`, `plugins/sqlseed-ai/src/sqlseed_ai/analyzer/`), verify with `Glob` that the path exists.

Record any missing paths as D1 violations (P1).

- [ ] **Step 2: Extract class/function names from CLAUDE.md and verify**

Read CLAUDE.md sections like "Key Modules", "Public API". For each class/function name (e.g., `DataOrchestrator`, `ColumnMapper`, `fill_table`), grep the codebase to verify it exists.

Record mismatches as D2 violations (P1).

- [ ] **Step 3: Verify count markers (D4)**

Read CLAUDE.md for AUTO-GENERATED markers:
- `<!-- BEGIN:AUTO-GENERATED:exact-match-rule-count -->75<!-- END -->`
- `<!-- BEGIN:AUTO-GENERATED:pattern-match-rule-count -->29<!-- END -->`

Run:
```bash
pytest tests/test_doc_sync.py -v
```

Expected: All tests pass. If any fail, the count markers are out of sync → D4 violation (P1).

- [ ] **Step 4: Verify hook count (D2/D4)**

CLAUDE.md states "Plugin Hooks (12 total)". Count hooks in `src/sqlseed/plugins/hookspecs.py`:

```
Grep pattern: ^@hookspec|def sqlseed_
path: c:\Users\14435\Desktop\sqlseed\src\sqlseed\plugins\hookspecs.py
output_mode: content, -n: true
```

If count != 12 → D4 violation (P1).

- [ ] **Step 5: Record all D1-D4 findings in `/tmp/audit_notes_layer4.md`**

---

## Task 9: Documentation alignment scan — D5-D10 (granularity)

**Files:**
- Read: `CLAUDE.md`, `README.md`, `ARCHITECTURE.md`, plugin READMEs

- [ ] **Step 1: Verify Public API signatures (D5)**

Read CLAUDE.md "Public API" table. For each function (`fill`, `connect`, `preview`, `fill_from_config`, `load_config`), read the actual signature in `src/sqlseed/__init__.py` and compare parameter names/types/defaults.

Record mismatches as D5 violations (P1).

- [ ] **Step 2: Verify README code examples are runnable (D6)**

Read `README.md` code blocks. For each Python example:
```python
from sqlseed import fill
fill("app.db", table="users", count=100)
```
Verify the function exists with the shown signature by reading `__init__.py`.

Record mismatches as D6 violations (P1).

- [ ] **Step 3: Verify rule numbers/behaviors (D7)**

CLAUDE.md mentions "Rule #14", "Rule #26". Verify in code:
```
Grep pattern: rule_14|_apply_rule_14|rule_26|_apply_rule_26
path: c:\Users\14435\Desktop\sqlseed\plugins\sqlseed-ai\src
output_mode: content, -n: true
```

Compare documented rule descriptions with actual implementation. Record mismatches as D7 (P1).

- [ ] **Step 4: Verify architecture description (D8)**

CLAUDE.md states "4 independent packages". Verify with `LS` that `src/sqlseed/`, `plugins/sqlseed-cli/`, `plugins/sqlseed-ai/`, `plugins/mcp-server-sqlseed/` all exist.

- [ ] **Step 5: Verify field types/constraints (D9)**

CLAUDE.md mentions `max_tokens` field with `ge=0`. Verify in `plugins/sqlseed-ai/src/sqlseed_ai/config.py`:
```
Grep pattern: max_tokens
path: c:\Users\14435\Desktop\sqlseed\plugins\sqlseed-ai\src\sqlseed_ai\config.py
output_mode: content, -n: true
```

Compare documented constraint with actual `Field(ge=0)`.

- [ ] **Step 6: Verify class diagrams (D10)**

Read ARCHITECTURE.md class diagrams. For key dataclasses (`GeneratorConfig`, `TableConfig`, `ColumnConfig`), read `src/sqlseed/config/models.py` and verify field names match.

- [ ] **Step 7: Record all D5-D10 findings in `/tmp/audit_notes_layer4.md`**

---

## Task 10: Consolidate findings and generate audit report

**Files:**
- Create: `docs/superpowers/specs/2026-07-04-naming-convention-audit-report.md`

- [ ] **Step 1: Read all notes files**

Read `/tmp/audit_notes_layer1.md`, `/tmp/audit_notes_layer2.md`, `/tmp/audit_notes_layer3.md`, `/tmp/audit_notes_layer4.md`.

- [ ] **Step 2: Deduplicate findings**

Merge all findings. Remove duplicates (same file:line + same dimension). Assign unique IDs (001, 002, ...).

- [ ] **Step 3: Generate report header**

Write to `docs/superpowers/specs/2026-07-04-naming-convention-audit-report.md`:

```markdown
# Naming Convention Audit Report

**Date:** 2026-07-04
**Auditor:** automated scan + manual review
**Spec:** docs/superpowers/specs/2026-07-04-naming-convention-audit-design.md
**Status:** Awaiting user per-item confirmation

## Summary Statistics

| Dimension | P0 | P1 | P2 | P3 | Subtotal |
|-----------|----|----|----|----|----------|
| S Spelling | TBD | TBD | TBD | TBD | TBD |
| P PEP8     | TBD | TBD | TBD | TBD | TBD |
| C Consistency | TBD | TBD | TBD | TBD | TBD |
| F File/Module | TBD | TBD | TBD | TBD | TBD |
| PC Project Conv | TBD | TBD | TBD | TBD | TBD |
| D Doc Alignment | TBD | TBD | TBD | TBD | TBD |
| **Total** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** |

## How to Read This Report

Each entry below will be marked by the user as:
- `✓` Agree to fix
- `✗` Disagree (keep current)
- `?` Needs discussion

After confirmation, fixes will be applied as atomic commits (one per rename target).
```

- [ ] **Step 4: Write dimension S section**

For each S finding, write:
```markdown
## 1. Spelling & Grammar (S)

### NNN | S1 | P0 | <file:line>

**Problem**: <description>
**Current**:
\`\`\`python
<code snippet>
\`\`\`
**Suggestion**: <fix>
**Rationale**: <PEP / best practice>
**Impact**: <call site count>
```

- [ ] **Step 5: Write dimension P section**

Same format for all PEP 8 findings (P1-P8).

- [ ] **Step 6: Write dimension C section**

Same format for all Consistency findings (C1-C7).

- [ ] **Step 7: Write dimension F section**

Same format for all File/Module findings (F1-F4).

- [ ] **Step 8: Write dimension PC section**

Same format for all Project Convention findings (PC1-PC4).

- [ ] **Step 9: Write dimension D section**

Same format for all Documentation Alignment findings (D1-D10).

- [ ] **Step 10: Update Summary Statistics table**

Replace all TBD cells with actual counts from the report.

- [ ] **Step 11: Commit the report**

```bash
git add docs/superpowers/specs/2026-07-04-naming-convention-audit-report.md
git commit -m "docs(audit): generate naming convention audit report (Stage 1)

4-layer scan complete: ruff N/F-rules + codespell + pattern grep +
manual read + documentation reverse-verify. Report covers 6 dimensions
(S/P/C/F/PC/D) with P0-P3 priority levels. Awaiting user per-item
confirmation before Stage 2 (atomic refactoring commits)."
```

---

## Task 11: Clean up temporary files

**Files:**
- Delete: `/tmp/audit_notes_layer1.md`, `/tmp/audit_notes_layer2.md`, `/tmp/audit_notes_layer3.md`, `/tmp/audit_notes_layer4.md`, `/tmp/ruff_n_findings.txt`, `/tmp/ruff_f_findings.txt`, `/tmp/codespell_findings.txt`

- [ ] **Step 1: Delete temp notes files**

Run:
```bash
rm -f /tmp/audit_notes_layer*.md /tmp/ruff_*_findings.txt /tmp/codespell_findings.txt
```

- [ ] **Step 2: Verify git status is clean**

Run:
```bash
git status
```

Expected: Only `docs/superpowers/specs/2026-07-04-naming-convention-audit-report.md` committed, no stray files.

---

## Task 12: Hand off to user for Stage 2 (per-item confirmation)

- [ ] **Step 1: Present report to user**

Output message:
> Stage 1 (scan & report) complete. Report saved to `docs/superpowers/specs/2026-07-04-naming-convention-audit-report.md`.
>
> Please review the report and mark each entry as `✓` (fix), `✗` (keep), or `?` (discuss). Once you've confirmed all entries, I'll create the Stage 2 implementation plan for atomic refactoring commits.

- [ ] **Step 2: Wait for user confirmation**

Do NOT proceed to Stage 2 until user provides marked-up report.

---

## Self-Review

### Spec coverage check

| Spec Section | Covered by Task |
|--------------|-----------------|
| 3.1 Dimension S (spelling) | Tasks 3, 4 |
| 3.2 Dimension P (PEP 8) | Task 2 |
| 3.3 Dimension C (consistency) | Task 5 |
| 3.4 Dimension F (file/module) | Tasks 6, 7 |
| 3.5 Dimension PC (project conventions) | Tasks 6, 7 |
| 3.6 Dimension D (doc alignment) | Tasks 8, 9 |
| 4.1 Layer 1 (ruff + codespell) | Tasks 1, 2, 3 |
| 4.2 Layer 2 (grep) | Tasks 4, 5 |
| 4.3 Layer 3 (manual read) | Tasks 6, 7 |
| 4.4 Layer 4 (doc scan) | Tasks 8, 9 |
| 5.1 Report file | Task 10 |
| 5.2 Entry format | Task 10 (steps 4-9) |
| 5.4 Report organization | Task 10 (steps 4-10) |
| 6.1 Stage 1 (scan & collect) | Tasks 1-11 |

No gaps. All spec sections covered.

### Placeholder scan

- Task 10 steps 4-9 use `<file:line>` / `<description>` / `<fix>` placeholders — these are **intentional template variables** filled by the actual scan findings, not plan placeholders. The engineer fills them with real data from Tasks 2-9.
- "TBD" in Summary Statistics table is intentional — filled in Step 10 after counting.
- No "TODO", "implement later", or vague instructions.

### Type consistency

- All tasks reference the same 6 dimensions (S/P/C/F/PC/D) consistently.
- Priority levels (P0-P3) consistent across spec and plan.
- File paths use consistent format throughout.

No issues found.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-04-naming-audit-stage1-scan-report.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
