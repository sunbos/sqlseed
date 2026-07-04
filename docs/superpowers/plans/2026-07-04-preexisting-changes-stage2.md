# Pre-existing Changes Stage 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Commit 47 pre-existing working-tree files (40 modified + 4 untracked + 6 deleted) as 8 atomic commits on `feat/llm-staged-yaml-analysis`, fixing `stream.py` regression and `ruff format` issues along the way.

**Architecture:** Layered commits following dependency direction (core → generators → ai plugin → tests). Each commit is self-contained: code + tests + doc-sync travel together so CI stays green at every node.

**Tech Stack:** Python 3.10+, ruff, mypy strict, pytest, lint-imports, codespell.

---

## Pre-commit Prerequisites

- [ ] **P0: Fix stream.py regression** — `while generated <= count` → `< count` (yields extra empty batch, breaks TestGenerateBatchSize, causes MemoryError in stress tests).
- [ ] **P0: Run `ruff format`** on 10 in-diff files: `schema_analyzer.py`, `stage_relevance.py`, `staged_analyzer.py`, `test_prompts_p0_p3.py`, `test_schema_analyzer.py`, `test_stage_relevance.py`, `test_staged_analyzer.py`, `test_auto_fix_generalization.py`, `stream.py`, `test_mapper.py`. Do NOT format the other 17 pre-existing files (would pollute commits).
- [ ] **P1: Verify `ruff check src/ tests/ plugins/` passes** after P0.
- [ ] **P1: Verify `pytest tests/test_architecture.py tests/test_doc_sync.py` passes** (26 SAFE_FUNCTIONS, 75 exact rules).

---

### Task 1: Remove temporary debugging/analysis files

**Files:**
- Delete: `_e2e_generation_report.md`, `_loop_results.md`, `_optimization_plan.md`, `_run_business_logic_loop.py`, `_verify_business_logic.py`, `complex_biz_schema_analysis.md`
- Delete (untracked): `.task15bak`

- [ ] **Step 1: Verify all 7 files exist**

```bash
git status --short | Select-String "_e2e_generation_report|_loop_results|_optimization_plan|_run_business_logic_loop|_verify_business_logic|complex_biz_schema_analysis|\.task15bak"
```

Expected: 7 matches (6 `D` + 1 `??`).

- [ ] **Step 2: Stage the 6 tracked deletions**

```bash
git add -u _e2e_generation_report.md _loop_results.md _optimization_plan.md _run_business_logic_loop.py _verify_business_logic.py complex_biz_schema_analysis.md
```

- [ ] **Step 3: Delete the untracked backup file**

```bash
Remove-Item .task15bak
```

- [ ] **Step 4: Verify staging**

```bash
git status --short | Select-String "^[AD]"
```

Expected: 6 `D :` entries, no `.task15bak`.

- [ ] **Step 5: Commit**

```bash
git commit -m "chore: remove temporary debugging/analysis files" -m "Remove scratch files from prior debugging sessions: _e2e_generation_report.md, _loop_results.md, _optimization_plan.md, _run_business_logic_loop.py, _verify_business_logic.py, complex_biz_schema_analysis.md. Also drop .task15bak (CLAUDE.md backup from Task 15 of naming audit)."
```

- [ ] **Step 6: Verify**

```bash
git log --oneline -1
git status --short | Measure-Object -Line
```

Expected: HEAD at new commit; 39 modified + 3 untracked remaining.

---

### Task 2: UNIQUE constraint `exclude_values` root-cause fix

**Files:**
- Modify: `src/sqlseed/core/constraints.py` (add `get_seen()`)
- Modify: `src/sqlseed/core/stream.py` (propagate `exclude_values`; **fix `<= count` regression**)
- Modify: `src/sqlseed/generators/_dispatch.py` (add `exclude_values` kwarg + 50-retry loop)
- Modify: `src/sqlseed/generators/_protocol.py` (Protocol signature)
- Modify: `tests/test_core/test_constraints.py` (TestGetSeen)
- Modify: `tests/test_core/test_stream.py` (TestAttemptNodeGenerationExcludeValues)
- Create: `tests/test_generators/test_dispatch_exclude.py`

- [ ] **Step 1: Fix the stream.py regression first**

Use Edit tool: `while generated <= count:` → `while generated < count:`

Verify:
```bash
git diff src/sqlseed/core/stream.py | Select-String "while generated"
```

Expected: `-while generated <= count:` and `+while generated < count:`.

- [ ] **Step 2: Stage all 7 files**

```bash
git add src/sqlseed/core/constraints.py src/sqlseed/core/stream.py src/sqlseed/generators/_dispatch.py src/sqlseed/generators/_protocol.py tests/test_core/test_constraints.py tests/test_core/test_stream.py tests/test_generators/test_dispatch_exclude.py
```

- [ ] **Step 3: Run targeted tests**

```bash
python -m pytest tests/test_core/test_constraints.py::TestGetSeen tests/test_core/test_stream.py::TestAttemptNodeGenerationExcludeValues tests/test_generators/test_dispatch_exclude.py -v
```

Expected: all pass.

- [ ] **Step 4: Run stress tests (regression check)**

```bash
python -m pytest tests/test_core/test_unique_exclude_integration.py -v --tb=short
```

Expected: all 42 pass (4 previous MemoryError failures fixed).

- [ ] **Step 5: Commit**

Write to `.git/COMMIT_MSG_TASK2`:

```
fix(core,generators): root-cause fix for UNIQUE + semantic generators

DataStream now passes ConstraintSolver.get_seen(col) as exclude_values
to the dispatch layer when a column has UNIQUE constraint. The dispatch
layer retries up to 50 attempts to avoid producing values already in
use, fixing the pattern where faker.email() etc. produce duplicates on
large row counts.

- constraints.py: add get_seen() returning a copy of seen values
- _dispatch.py: add exclude_values kwarg + 50-retry loop
- _protocol.py: update DataProvider.generate signature
- stream.py: propagate exclude_values from _attempt_node_generation
- stream.py: fix regression `while generated <= count` -> `< count`
  (the <= variant yielded an extra empty batch, breaking TestGenerateBatchSize
  and causing MemoryError in 1000-row stress tests)
- test_dispatch_exclude.py: 7 new tests (backward compat, dedup, exhaustion)
```

```bash
git commit -F .git/COMMIT_MSG_TASK2
```

- [ ] **Step 6: Verify**

```bash
git log --oneline -1
git status --short | Measure-Object -Line
```

Expected: HEAD at new commit; 32 modified + 3 untracked remaining.

---

### Task 3: Charset aliases for LLM-emitted variants

**Files:**
- Modify: `src/sqlseed/generators/_string_helpers.py`
- Modify: `tests/test_generators/test_string_helpers.py`

- [ ] **Step 1: Stage the 2 files**

```bash
git add src/sqlseed/generators/_string_helpers.py tests/test_generators/test_string_helpers.py
```

- [ ] **Step 2: Run tests**

```bash
python -m pytest tests/test_generators/test_string_helpers.py -v
```

Expected: all pass (8 alias tests + case-sensitivity test).

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(generators): charset aliases for LLM-emitted variants" -m "resolve_charset() now recognises common LLM-emitted aliases: alphanum/letters_digits/ascii_letters_digits -> alphanumeric, letters/ascii_letters -> alpha, numeric/numbers -> digits. Aliases are case-sensitive (custom charsets can be anything)."
```

- [ ] **Step 4: Verify**

```bash
git log --oneline -1
```

Expected: HEAD at new commit; 30 modified + 3 untracked remaining.

---

### Task 4: `timedelta` in expression SAFE_FUNCTIONS (25 → 26)

**Files:**
- Modify: `src/sqlseed/core/expression.py`
- Modify: `tests/test_core/test_expression.py`
- Modify: `tests/test_architecture.py` (count 22 → 26)
- Modify: `src/sqlseed/core/AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/guide.md`

- [ ] **Step 1: Stage all 8 files**

```bash
git add src/sqlseed/core/expression.py tests/test_core/test_expression.py tests/test_architecture.py src/sqlseed/core/AGENTS.md CLAUDE.md README.md README.zh-CN.md docs/guide.md
```

- [ ] **Step 2: Run targeted tests**

```bash
python -m pytest tests/test_core/test_expression.py tests/test_architecture.py::TestCountContracts -v
```

Expected: all pass (count == 26).

- [ ] **Step 3: Run doc sync tests**

```bash
python -m pytest tests/test_doc_sync.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

Write to `.git/COMMIT_MSG_TASK4`:

```
feat(core): add timedelta to expression SAFE_FUNCTIONS (25 -> 26)

Enables date arithmetic in derived expressions, e.g.
`value + timedelta(days=7)` to advance a date source column by a week.
Only days/seconds units exposed to keep sandbox minimal.

- expression.py: add timedelta(days, seconds) to SAFE_FUNCTIONS
- test_expression.py: 3 new tests (days, seconds, count=26)
- test_architecture.py: SAFE_FUNCTIONS count 22 -> 26 (also fixes
  pre-existing doc/test mismatch where test asserted 22 but code had 25)
- Sync docs: CLAUDE.md, README.md, README.zh-CN.md, docs/guide.md,
  src/sqlseed/core/AGENTS.md (25 -> 26)
```

```bash
git commit -F .git/COMMIT_MSG_TASK4
```

- [ ] **Step 5: Verify**

```bash
git log --oneline -1
git status --short | Measure-Object -Line
```

Expected: HEAD at new commit; 22 modified + 3 untracked remaining.

---

### Task 5: `sku` and `*_no`/`*_nbr` mapper rules (74 → 75 exact rules)

**Files:**
- Modify: `src/sqlseed/core/mapper.py`
- Modify: `tests/test_mapper.py`
- Modify: `tests/test_mapper_camelcase.py`
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/architecture.md`
- Modify: `docs/architecture.zh-CN.md`

- [ ] **Step 1: Stage all 8 files**

```bash
git add src/sqlseed/core/mapper.py tests/test_mapper.py tests/test_mapper_camelcase.py CLAUDE.md README.md README.zh-CN.md docs/architecture.md docs/architecture.zh-CN.md
```

- [ ] **Step 2: Run targeted tests**

```bash
python -m pytest tests/test_mapper.py tests/test_mapper_camelcase.py -v
```

Expected: all pass.

- [ ] **Step 3: Run doc sync tests**

```bash
python -m pytest tests/test_doc_sync.py -v
```

Expected: all pass (75 exact rules synced).

- [ ] **Step 4: Commit**

Write to `.git/COMMIT_MSG_TASK5`:

```
fix(mapper): sku and *_no/*_nbr columns map to alphanumeric string (74 -> 75 exact rules)

SKUs and business codes (order_no, task_no, invoice_nbr) must be
alphanumeric (no spaces/dashes) - they are used as identifiers in URLs,
barcodes, and joins. The default string charset includes ' _-' which is
unsafe.

- mapper.py: add sku exact rule (alphanumeric, 6-12 chars)
- mapper.py: change *_no/*_nbr pattern from foreign_key_or_integer to
  string (alphanumeric) - *_no is a business code, not an FK
- test_mapper.py: 4 new regression tests
- test_mapper_camelcase.py: update assertions
- Sync docs: 74 -> 75 exact rules (CLAUDE.md, README, architecture)
```

```bash
git commit -F .git/COMMIT_MSG_TASK5
```

- [ ] **Step 5: Verify**

```bash
git log --oneline -1
git status --short | Measure-Object -Line
```

Expected: HEAD at new commit; 14 modified + 3 untracked remaining.

---

### Task 6: Stage3Validator Rules #17-#26 + UNIQUE enrichment

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py` (+1306 lines)
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/_prompts.py`
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/stage_relevance.py`
- Modify: `plugins/sqlseed-ai/tests/test_staged_analyzer.py` (+2278 lines)
- Modify: `plugins/sqlseed-ai/tests/test_stage_relevance.py`

- [ ] **Step 1: Stage all 5 files**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py plugins/sqlseed-ai/src/sqlseed_ai/_prompts.py plugins/sqlseed-ai/src/sqlseed_ai/stage_relevance.py plugins/sqlseed-ai/tests/test_staged_analyzer.py plugins/sqlseed-ai/tests/test_stage_relevance.py
```

- [ ] **Step 2: Run targeted tests**

```bash
python -m pytest plugins/sqlseed-ai/tests/test_staged_analyzer.py plugins/sqlseed-ai/tests/test_stage_relevance.py -v --tb=short
```

Expected: all pass (53+ new tests for Rules #17-#26).

- [ ] **Step 3: Run ruff check on staged files**

```bash
git diff --cached --name-only | ForEach-Object { ruff check $_ }
```

Expected: no errors.

- [ ] **Step 4: Commit**

Write to `.git/COMMIT_MSG_TASK6`:

```
feat(ai): Stage3Validator rules #17-#26 + UNIQUE constraint enrichment

Stage3Validator expanded with 10 new auto-fix rules on top of LLM output:
  Rule #17: boolean-expression derive_from detection (type-aware for DATE)
  Rule #18: cap unreasonable future end_year to current_year + 1
  Rule #19: extract min/max_value from simple CHECK constraints
  Rule #20: rewrite sandbox-external functions (floor/random -> random_int)
  Rule #22: isolate end_date year range for cross-column date CHECK
  Rule #23: upgrade phone-like columns to NANP pattern
  Rule #24: upgrade UNIQUE word/string to template (derive prefix from name)
  Rule #25: convert text -> string for code-like columns
  Rule #26: coerce random_float -> random_int for INTEGER columns

Also adds _enrich_unique_constraints_from_db() to work around SQLAlchemy's
inspector.get_indexes() filtering out sqlite_autoindex_* (column-level
UNIQUE), keeping features.tables[i].unique_constraints populated.

_prompts.py: template prefix now derived from table/column name (DEPT-,
EMP-) instead of hardcoded MER-; *_code columns PREFER template (NOT
string) for UNIQUE safety.
```

```bash
git commit -F .git/COMMIT_MSG_TASK6
```

- [ ] **Step 5: Verify**

```bash
git log --oneline -1
git status --short | Measure-Object -Line
```

Expected: HEAD at new commit; 9 modified + 3 untracked remaining.

---

### Task 7: Rule #14 backport to legacy refiner/schema_analyzer

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/refiner.py`
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/schema_analyzer.py`
- Modify: `plugins/sqlseed-ai/tests/test_refiner.py`
- Modify: `plugins/sqlseed-ai/tests/test_schema_analyzer.py`
- Create: `plugins/sqlseed-ai/tests/test_auto_fix_generalization.py`
- Modify: `plugins/sqlseed-ai/tests/test_prompts_p0_p3.py` (isort fix)

- [ ] **Step 1: Stage all 6 files**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/refiner.py plugins/sqlseed-ai/src/sqlseed_ai/schema_analyzer.py plugins/sqlseed-ai/tests/test_refiner.py plugins/sqlseed-ai/tests/test_schema_analyzer.py plugins/sqlseed-ai/tests/test_auto_fix_generalization.py plugins/sqlseed-ai/tests/test_prompts_p0_p3.py
```

- [ ] **Step 2: Run targeted tests**

```bash
python -m pytest plugins/sqlseed-ai/tests/test_refiner.py::TestRule14ParamStripping plugins/sqlseed-ai/tests/test_schema_analyzer.py plugins/sqlseed-ai/tests/test_auto_fix_generalization.py -v --tb=short
```

Expected: all pass.

- [ ] **Step 3: Run ruff check on staged files**

```bash
git diff --cached --name-only | ForEach-Object { ruff check $_ }
```

Expected: no errors (including previously-failing isort in `test_prompts_p0_p3.py`).

- [ ] **Step 4: Commit**

Write to `.git/COMMIT_MSG_TASK7`:

```
fix(ai): apply Rule #14 in legacy refiner/schema_analyzer paths

The legacy (non-staged) path used by `ai-suggest` without
--staged-pipeline was missing Rule #14 (strip invalid generator params),
causing ConfigurationError when LLMs hallucinate params like email's
min_length/example. Now both refiner.py and schema_analyzer.py delegate
to Stage3Validator._apply_rule_14_strip_invalid_params via lazy import
(avoids circular dependency).

- refiner.py: add _apply_rule_14_param_stripping() helper
- schema_analyzer.py: integrate Rule #14 in _auto_fix_config;
  expand Fix 11 to catch ANY non-matching generator (not just 'string')
  on email/phone columns; preserve 'pattern' generator (custom regex)
- test_refiner.py: TestRule14ParamStripping (6 tests)
- test_schema_analyzer.py: 9 new tests (call_llm retry, Fix 11
  generalization, Rule #14)
- test_auto_fix_generalization.py: adversarial tests using HR/school/
  hospital schemas (avoid self-proving trap on complex_biz.db)
- test_prompts_p0_p3.py: fix isort import order
```

```bash
git commit -F .git/COMMIT_MSG_TASK7
```

- [ ] **Step 5: Verify**

```bash
git log --oneline -1
git status --short
```

Expected: HEAD at new commit; only `test_ai_plugin.py`, `test_cli.py` modified + 2 untracked remaining.

---

### Task 8: Environment-dependent test robustness

**Files:**
- Modify: `plugins/sqlseed-ai/tests/test_ai_plugin.py`
- Modify: `plugins/sqlseed-cli/tests/test_cli.py`

- [ ] **Step 1: Stage the 2 files**

```bash
git add plugins/sqlseed-ai/tests/test_ai_plugin.py plugins/sqlseed-cli/tests/test_cli.py
```

- [ ] **Step 2: Run targeted tests**

```bash
python -m pytest plugins/sqlseed-ai/tests/test_ai_plugin.py plugins/sqlseed-cli/tests/test_cli.py -v --tb=short
```

Expected: all pass.

- [ ] **Step 3: Commit**

Write to `.git/COMMIT_MSG_TASK8`:

```
test(ai,cli): robustness fixes for environment-dependent tests

- test_ai_plugin.py: clear SQLSEED_AI_MODEL env var in auto-detect test
  (was short-circuiting on leaked model from prior session); compute
  expected message count from FEW_SHOT_EXAMPLES (was hardcoded to 10,
  broke at 14); replace localhost:9999 connection-failure test with
  deterministic monkeypatched call_llm (was environment-dependent)
- test_cli.py: force google_ai_studio backend + empty cache dir for
  'no API key' tests (was environment-dependent when LM Studio running)
```

```bash
git commit -F .git/COMMIT_MSG_TASK8
```

- [ ] **Step 4: Verify clean working tree**

```bash
git status --short
```

Expected: only `?? docs/superpowers/plans/2026-07-02-llm-staged-yaml-analysis.md` remains.

---

### Task 9 (optional): Stage 2 plan document

**Files:**
- Create: `docs/superpowers/plans/2026-07-02-llm-staged-yaml-analysis.md` (165KB)

- [ ] **Step 1: Decide whether to commit plan docs**

```bash
git ls-files docs/superpowers/plans/ | Measure-Object -Line
```

If >0, plans are tracked; commit. If 0, skip.

- [ ] **Step 2 (if committing): Commit**

```bash
git add docs/superpowers/plans/2026-07-02-llm-staged-yaml-analysis.md
git commit -m "docs(ai): add staged pipeline implementation plan"
```

---

### Task 10: Final CI verification

- [ ] **Step 1: Run full static checks**

```bash
ruff check src/ tests/ plugins/
mypy
lint-imports
codespell src/ tests/ plugins/
```

Expected: all pass.

- [ ] **Step 2: Run ruff format check**

```bash
ruff format --check src/ tests/ plugins/
```

Expected: only pre-existing 17 files (outside this Stage) may need formatting. All 10 in-diff files clean.

- [ ] **Step 3: Run core test suites**

```bash
python -m pytest tests/test_architecture.py tests/test_doc_sync.py tests/test_core/test_constraints.py tests/test_core/test_column_dag.py tests/test_core/test_expression.py tests/test_core/test_stream.py tests/test_core/test_unique_exclude_integration.py -v
```

Expected: all pass (including 4 previously-failing stress tests).

- [ ] **Step 4: Run plugin test suites**

```bash
python -m pytest plugins/sqlseed-ai/tests/ plugins/sqlseed-cli/tests/ -v --tb=short
```

Expected: all pass.

- [ ] **Step 5: Verify commit history**

```bash
git log --oneline -10
```

Expected: 8 new commits (Tasks 1-8) on top of `a5e884b`.

- [ ] **Step 6: Verify working tree clean**

```bash
git status
```

Expected: "nothing to commit, working tree clean" or only optional plan doc untracked.

---

## Self-Review

### 1. Spec coverage
- All 40 modified files accounted for: Yes (Tasks 2-8).
- All 4 untracked files accounted for: Yes (Task 1: .task15bak; Task 2: test_dispatch_exclude.py; Task 7: test_auto_fix_generalization.py; Task 9: staged-yaml-analysis.md).
- All 6 deleted files accounted for: Yes (Task 1).
- Known bugs fixed: Yes (stream.py `<= count` in Task 2 Step 1; ruff format in Pre-commit Prerequisites; test_architecture count in Task 4).

### 2. Placeholder scan
- No "TBD", "TODO", "implement later" in this plan.
- All steps have exact commands and expected outputs.
- Commit messages are complete drafts.

### 3. Type consistency
- `exclude_values` parameter name consistent across `_dispatch.py`, `_protocol.py`, `stream.py`, `test_dispatch_exclude.py`.
- `get_seen()` method name consistent across `constraints.py`, `stream.py`, `test_constraints.py`.
- `Stage3Validator._apply_rule_14_strip_invalid_params` method name consistent across `staged_analyzer.py` (Task 6), `refiner.py` + `schema_analyzer.py` (Task 7).
- Count updates consistent: 25→26 (SAFE_FUNCTIONS), 74→75 (exact rules), 22→26 (test_architecture assertion).

### 4. Dependency order
- Task 1 (cleanup) first — no dependencies.
- Task 2 (UNIQUE fix) before Task 6 (staged pipeline Rule #24 builds on UNIQUE theme).
- Task 6 (Stage3Validator) before Task 7 (Rule #14 backport lazy-imports Stage3Validator).
- Tasks 3, 4, 5 independent of each other and of Tasks 6-7.
- Task 8 (test robustness) last — independent.

### 5. CI green at every commit
- Task 1: pure deletion, no CI impact.
- Task 2: includes `<= count` fix + tests, so stress tests pass.
- Task 3: includes tests, self-contained.
- Task 4: includes test_architecture count update + doc sync, so `test_doc_sync.py` passes.
- Task 5: includes doc sync, so `test_doc_sync.py` passes.
- Task 6: includes 53+ tests, self-contained.
- Task 7: includes tests + isort fix, so `ruff check` passes.
- Task 8: includes tests, self-contained.

All commits should leave CI green.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-04-preexisting-changes-stage2.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
