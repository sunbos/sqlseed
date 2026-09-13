# LLM Validation Loop Engineering Design

**Date:** 2026-07-09
**Status:** Draft (pending self-review and user approval)
**Branch:** `feat/contract-driven-self-healing`
**Predecessor spec:** `2026-07-09-data-quality-demo-coverage-design.md`

## Goal

Validate the sqlseed project code (core + sqlseed-ai plugin) against all 8
databases in `data_quality_demo/` using a local LM Studio Gemma 4 model, and
iteratively fix project code blind spots via the Loop Engineering methodology
until all databases produce correct, fully-populated test data across 5
correctness dimensions.

**Non-goal:** Modify database SQL files (already covered by predecessor spec)
or manually patch LLM-generated YAML outputs (forbidden by Loop Engineering
discipline — fixes must land in CODE, not in outputs).

## Scope

### In Scope

- R1-R7 SQLite databases: full validation (ai-analyze → fill → verify → fix)
- R8 PostgreSQL database: deferred until Docker/PG environment ready (separate
  follow-up spec); this spec only covers SQLite path
- Project code modifications in `src/sqlseed/` and `plugins/sqlseed-ai/` that
  are **generic improvements** (benefit any database, not just data_quality_demo)
- Markdown documentation sync for any logic changes
- 5-dimension correctness verification

### Out of Scope

- Manual YAML patching (forbidden)
- Business-logic-specific code in core (forbidden — see Section 4)
- R8 PostgreSQL runtime validation (deferred to Docker follow-up)
- Database SQL file modifications (covered by predecessor spec, already done)

## Section 1: Approach Selection

**Selected: Hybrid Iteration (Plan C)** — 4-phase workflow that minimizes LLM
calls while maximizing problem root-cause clarity.

**Rationale:**
- Phase 1 reuses a single LLM scan per database (7 calls total) as the
  baseline; no re-runs unless YAML itself is structurally broken
- Phase 2 fixes project code by blind-spot TYPE (not by database), so a single
  fix can resolve issues across multiple databases simultaneously
- Phase 3 reuses existing YAMLs via the v4 validator revalidation path (no LLM
  calls) — directly aligned with Loop Engineering Discipline #4
  ("avoid LLM re-runs")
- Phase 4 reserved for the rare case where YAML structure itself is wrong
  (e.g., LLM emitted a generator that does not exist), not for code blind spots

**Phase 1 LLM execution mode: Serial** — one ai-analyze at a time, allowing
real-time log inspection and stable LM Studio throughput on a single loaded
model.

## Section 2: 4-Phase Workflow

### Phase 1 — Full Scan (7 LLM calls, one per database)

For each database Ri (i=1..7), **serially**:

1. Build SQLite DB: `sqlite3 r{i}_*.db < data_quality_demo/r{i}_*.sql`
2. Run ai-analyze with LLM logging:
   ```
   sqlseed ai-analyze \
     --db r{i}_*.db \
     --output r{i}_config.yaml \
     --base-url http://127.0.0.1:1234/v1 \
     --log-llm r{i}_llm.log \
     --max-retries 3
   ```
   - Do NOT manually inspect or edit the YAML during this phase
   - The `--log-llm` flag captures full LLM interaction for D4 (pattern
     recognition accuracy) analysis
3. Fill the DB:
   ```
   sqlseed fill --config r{i}_config.yaml --db r{i}_*.db
   ```
4. Run 5-dimension verification (see Section 3):
   ```
   python scripts/_verify_r{i}.py  # temporary script, not committed
   ```
5. Collect: `Report_i` + `r{i}_llm.log` + `r{i}_config.yaml` + `r{i}_*.db`

**Phase 1 output:** A consolidated blind-spot catalog, grouped by **blind-spot
TYPE** (not by database):
- Type A: CHECK pattern recognition miss (LLM did not infer correct generator
  for a known Pattern 1-36)
- Type B: Semantic generator miss (LLM picked wrong generator type — e.g.,
  `string` for an `email` column)
- Type C: Constraint execution failure (FK/CHECK/UNIQUE violation at fill time)
- Type D: Data distribution issue (all-NULL column, single-value column,
  out-of-range distribution)
- Type E: Cross-database compatibility issue (SQLite-only construct that would
  fail on PG)

### Phase 2 — Unified Code Fixes (no LLM calls)

For each blind-spot type, locate the root cause in project code and fix it:

| Blind-spot Type | Likely Code Location | Fix Pattern |
|----------------|----------------------|-------------|
| Type A (pattern miss) | `plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py` — `_infer_cross_column_config` / `_parse_single_column_check` | Add missing regex pattern; add unit test |
| Type A (post-LLM safety net miss) | `auto_heal/orchestrator.py` — Step 5.5 | Add new safety-net rule; add unit test |
| Type B (semantic miss) | `repair/strategies.py` — `_semantic_upgrade`; OR `auto_heal/orchestrator.py` — Step 4 / Step 5.5 delegation to `ColumnMapper.map_column()` | Improve semantic upgrade or ColumnMapper delegation; add unit test |
| Type C (constraint execution) | `src/sqlseed/core/unique_adjuster.py`, `src/sqlseed/core/constraints.py`, `src/sqlseed/core/stream.py` | Fix constraint solver / FK sampler; add unit test |
| Type D (distribution) | `src/sqlseed/generators/` provider params; OR `auto_heal/orchestrator.py` derive_from handling | Adjust generator param defaults; add unit test |
| Type E (cross-DB compat) | `src/sqlseed/database/` adapter / dialect | Generic adapter improvement; add unit test |

**Each fix:**
1. Write failing unit test (TDD)
2. Implement minimal fix
3. Run `pytest <test_file> -v` — must pass
4. Run `ruff check src/ tests/ plugins/` — must pass
5. Run `mypy` — must pass
6. Commit to `feat/contract-driven-self-healing` branch with English message:
   `<type>: <root cause> in <module> (blind-spot type <X>)`

### Phase 3 — Revalidation Reusing Existing YAMLs (no LLM calls)

For each database Ri:

1. Rebuild DB: `sqlite3 r{i}_*.db < data_quality_demo/r{i}_*.sql` (fresh)
2. **Reuse** `r{i}_config.yaml` from Phase 1 (no ai-analyze re-run)
3. Re-run v4 validator on the YAML:
   ```
   python scripts/_revalidate.py r{i}_config.yaml r{i}_*.db
   ```
   This invokes the v4 `FastValidator` + `REPAIR_STRATEGIES` pipeline on the
   existing YAML — exactly the same code path as ai-analyze, but without the
   LLM call. If a fix in Phase 2 changed the validator's behavior, the
   revalidation will reflect it.
4. Fill the DB:
   ```
   sqlseed fill --config r{i}_config.yaml --db r{i}_*.db
   ```
5. Run 5-dimension verification again → `Report_i_phase3`

**Convergence check:**
- If `Report_i_phase3` is fully clean → Ri is done, mark as converged
- If `Report_i_phase3` shows remaining issues → those are YAML-structural
  (Phase 4) OR new blind spots (back to Phase 2)

### Phase 4 — Targeted LLM Re-runs (only when necessary)

For each database Ri that still fails Phase 3:

1. Diagnose: Is the failure due to YAML structural error (e.g., LLM emitted a
   non-existent generator) or code blind spot (e.g., a CHECK pattern still not
   recognized)?
   - **YAML structural** → Phase 4 LLM re-run
   - **Code blind spot** → back to Phase 2 (do NOT re-run LLM)
2. If YAML structural: re-run ai-analyze for Ri only:
   ```
   sqlseed ai-analyze --db r{i}_*.db --output r{i}_config_v2.yaml --base-url ...
   ```
3. Fill + verify with new YAML
4. If still failing → diagnose again (Phase 2 or Phase 4)

**Convergence criterion:** All 7 databases pass 5-dimension verification with
0 critical violations (FK/CHECK/UNIQUE/NOT NULL) and 0 critical semantic
errors (malformed email/phone/url, out-of-range dates, illegal enum values).

## Section 3: 5-Dimension Verification

For each database, run a verification script that checks all 5 dimensions:

### D1 — Structural Integrity (mandatory, zero tolerance)

```sql
-- FK integrity: for every FK column, count orphan rows
SELECT COUNT(*) FROM child c LEFT JOIN parent p ON c.fk = p.id WHERE p.id IS NULL;
-- Must be 0 for every FK

-- CHECK violations: SQLite allows introspecting CHECK but not direct
-- violation count. Instead, run a validation query per CHECK constraint:
-- e.g., for "CHECK (price > 0)": SELECT COUNT(*) FROM products WHERE price <= 0;

-- UNIQUE violations:
SELECT col, COUNT(*) FROM t GROUP BY col HAVING COUNT(*) > 1;

-- NOT NULL violations:
SELECT COUNT(*) FROM t WHERE col IS NULL;  -- for NOT NULL columns
```

**Pass criterion:** All counts = 0.

### D2 — Field Semantic Correctness (mandatory, zero tolerance for critical fields)

- `email` columns: regex `^[^@]+@[^@]+\.[^@]+$` — 100% match
- `phone` columns: digit count matches CHECK constraint LENGTH requirement
- `url` columns: starts with `http://` or `https://`
- `uuid` columns: UUID format
- `isbn`, `iban`, `vin`, `passport`, `ssn` columns: format / checksum valid
- Date columns: within reasonable range (e.g., birth_date not in future,
  not before 1900)
- Enum columns: value in declared enum set

**Pass criterion:** 100% of critical semantic fields valid; warnings allowed
for non-critical fields.

### D3 — Data Distribution Reasonableness

- No all-NULL columns (unless column is intentionally optional and
  null_ratio=1.0 in YAML)
- No single-value columns (cardinality >= 2 for non-boolean columns)
- Numeric columns: distribution within CHECK range; no degenerate distribution
  (e.g., all values = min)
- Date columns: reasonable spread, not all the same date
- Boolean columns: both 0 and 1 present (unless business logic dictates
  otherwise)

**Pass criterion:** No all-NULL columns; no single-value columns (warnings
allowed for legitimate cases).

### D4 — Pattern Recognition Accuracy

From the `--log-llm` JSON log, extract:
- Which CHECK constraints the LLM identified
- Which generator type the LLM assigned to each column
- Which derive_from expressions the LLM generated

Cross-check against the actual CHECK constraints in the database schema:
- For each Pattern 1-36 in the schema, was it correctly identified?
- For each derive_from expression, does it satisfy the CHECK constraint?

**Pass criterion:** >= 95% pattern recognition accuracy; misses logged as
Type A blind spots for Phase 2.

### D5 — Cross-Database Compatibility (SQLite + PG dual-angle)

For R1-R7 (SQLite-validated):
- Static check: every CHECK constraint uses portable SQL (no SQLite-only
  functions like `DATE('30 days')`)
- Static check: no `PRAGMA` statements
- Static check: no `AUTOINCREMENT` (use `INTEGER PRIMARY KEY` for SQLite +
  note PG equivalent)
- Static check: no forward FK references (referenced table must exist first)
- Static check: no subquery in CHECK

For R8 (deferred to Docker follow-up):
- Actually run on PostgreSQL via testcontainers
- Verify PG-specific types (uuid, JSONB, inet, cidr, macaddr, interval,
  text[], tsvector) work end-to-end
- Verify EXCLUDE constraint, expression indexes, full-text search indexes

**Pass criterion (R1-R7):** All static checks pass.
**Pass criterion (R8):** Deferred (separate spec).

## Section 4: Core Code Modification Boundary

Per user constraint: "不能将业务逻辑放到核心代码中，项目是长期主义，核心代码
要保证稳定性所以不能有业务逻辑的增加，但是不代表不能修改，如果有利于项目长期
发展是可以修改的"

### Allowed Modifications (generic improvements)

| Location | Allowed If... |
|----------|--------------|
| `plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py` | The fix improves pattern recognition for ANY database, not just data_quality_demo. Example: adding Pattern 8e recognition benefits any DB with `col >= X AND col < other_col`. |
| `plugins/sqlseed-ai/src/sqlseed_ai/repair/strategies.py` | The fix improves repair strategy generically. Example: `_semantic_upgrade` preserving CHECK params benefits any DB with LENGTH + phone-like columns. |
| `src/sqlseed/core/mapper.py` | The fix adds generic column-name-to-generator semantic mapping. Example: mapping `email` column name → `email` generator benefits any DB. |
| `src/sqlseed/core/schema.py` | The fix improves generic schema inference. Example: merging UNIQUE detection from multiple sources benefits any DB. |
| `src/sqlseed/core/unique_adjuster.py` | The fix improves generic UNIQUE enforcement. |
| `src/sqlseed/core/stream.py` | The fix improves generic FK sampling or constraint handling. |
| `src/sqlseed/database/` | The fix is a generic adapter/dialect improvement. |

### Forbidden Modifications (business-logic pollution)

| Forbidden | Reason |
|-----------|--------|
| Hardcoding `data_quality_demo` paths in source code | Business-specific |
| Hardcoding specific column names like `r1_phone`, `r6_iban` in core | Business-specific |
| Adding a CHECK constraint pattern that only matches one specific table in data_quality_demo | Business-specific (the pattern must be generic) |
| Adding special-case logic for one database schema | Business-specific |
| Bypassing the ColumnMapper to force a specific generator for one column | Business-specific |

### Decision Test

Before any code modification, apply this test:
> "If a completely different database (e.g., a HR system, a gaming leaderboard,
> a scientific dataset) had the same construct, would this fix benefit it?"

- **Yes** → Generic improvement, allowed
- **No** → Business-logic pollution, forbidden

## Section 5: Markdown Documentation Sync

Per user constraint #5: "修改重要逻辑时，不要忘记更新项目所有涉及到的markdown文档"

### Sync Rules

| Source File Modified | Docs to Update |
|---------------------|----------------|
| `auto_heal/orchestrator.py` — new Pattern added | `CLAUDE.md` (pattern count), `README.md` / `README.zh-CN.md` (if pattern count is documented) |
| `repair/strategies.py` — new repair strategy | `CLAUDE.md` (v4 contract-driven section) |
| `core/mapper.py` — new exact match rule | `CLAUDE.md`, `README.md` (exact-match-rule-count marker), run `scripts/sync_docs.py` |
| `core/schema.py` — new schema inference method | `CLAUDE.md` (Key Modules section) |
| `plugins/hookspecs.py` — new hook | `CLAUDE.md`, `README.md`, `docs/architecture.md` (hook table) |
| Any file with AUTO-GENERATED markers | Run `pytest tests/test_doc_sync.py` to verify; run `scripts/sync_docs.py` to regenerate |

### Sync Discipline

- Each Phase 2 fix commit that modifies logic MUST include corresponding doc
  updates in the same commit
- Run `pytest tests/test_doc_sync.py` before each commit to verify count markers
- Run `ruff check` + `mypy` before each commit

## Section 6: Loop Engineering Discipline

Per user constraint #2: "使用loop engineering工程完成"

### Per-Round Discipline (carried over from established methodology)

1. **Observe**: Read fill failure log, generated YAML, verification report;
   locate failing tables and failing constraints
2. **Diagnose**: Trace forward along the code path (fill → DataStream →
   ConstraintSolver → v4 validator → Pattern N), find where it was skipped /
   misjudged
3. **Hypothesize**: Classify root cause — LLM error / multi-CHECK chain /
   detection blind spot / rule ordering
4. **Fix CODE**: Fix at the correct layer (validator rule, adapter method,
   orchestrator logic), with detailed comments explaining WHY
5. **Revalidate**: Use revalidation script on existing YAML to verify the fix,
   no LLM re-run needed
6. **Fill test**: Rebuild DB → `sqlseed fill --config` → check all tables pass
7. **Test suite**: `pytest` relevant test files all pass

### Per-Round Tracking

- Track per-database convergence: `Round N: Ri M/M tables passed`
- Compare Round N vs Round N-1 to identify new regressions
- A fix must "resolve current failure WITHOUT introducing new regression"
- Convergence curve example: R1 8/12 → 11/12 → 12/12 (converged)

### Commit & Cleanup Discipline

- English commit messages: `<type>: <root cause> in <module> (blind-spot type <X>)`
- Only `git add` source files (never `git add -A`)
- Clean up all temporary files (YAML backups, logs, DBs, temp scripts) after
  each round — keep working tree clean
- Temporary verification scripts go in `scripts/_*.py` (underscore prefix
  excluded from git)

### Non-Interference Discipline (user constraint #3)

- The assistant (this AI) is a SUPERVISOR, not a participant in the LLM
  analysis flow
- The assistant does NOT manually patch YAML outputs to "pass tests"
- The assistant does NOT manually edit DB files to "fix" FK violations
- All fixes land in project CODE (validator rules, adapter methods,
  orchestrator logic)
- The LLM generates YAML autonomously; the assistant only observes the result
  and the LLM log, then fixes CODE if the result is wrong

## Section 7: Verification Script Design

A temporary Python script (not committed to git) that runs all 5 dimensions:

```python
# scripts/_verify_data_quality.py
# Temporary, not committed. Underscore prefix excluded from git.

import sqlite3
import re
from dataclasses import dataclass
from typing import Any

@dataclass
class Report:
    db_name: str
    d1_structural: dict[str, int]  # check_name -> violation_count
    d2_semantic: dict[str, int]    # field_name -> invalid_count
    d3_distribution: dict[str, str]  # column -> issue_description
    d4_pattern_accuracy: float     # 0.0 - 1.0
    d5_compat: dict[str, bool]     # check_name -> passed
    @property
    def passed(self) -> bool:
        return (
            all(v == 0 for v in self.d1_structural.values())
            and all(v == 0 for v in self.d2_semantic.values())
            and self.d4_pattern_accuracy >= 0.95
            and all(self.d5_compat.values())
        )

def verify(db_path: str, yaml_path: str, llm_log_path: str | None = None) -> Report:
    conn = sqlite3.connect(db_path)
    # ... D1: iterate all CHECK constraints, count violations
    # ... D2: regex-check email/phone/url/uuid columns
    # ... D3: cardinality + NULL ratio per column
    # ... D4: parse llm_log JSON, compare identified patterns to actual CHECKs
    # ... D5: static checks on schema SQL
    return Report(...)

if __name__ == "__main__":
    import sys
    report = verify(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    print(report)
    sys.exit(0 if report.passed else 1)
```

## Section 8: Convergence Criteria

A database Ri is **converged** when:

1. **D1 Structural**: All FK/CHECK/UNIQUE/NOT NULL violations = 0
2. **D2 Semantic**: All critical fields (email/phone/url/uuid/date/enum) 100% valid
3. **D3 Distribution**: No all-NULL columns; no single-value columns (warnings allowed)
4. **D4 Pattern**: >= 95% of CHECK patterns correctly identified by LLM
5. **D5 Compat**: All static cross-DB checks pass

The project is **fully converged** when all 7 databases (R1-R7) meet these
criteria simultaneously with the same project code.

## Section 9: Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| LM Studio throughput too slow | Serial execution chosen; if a single ai-analyze > 5 min, consider `--ultra-compact` prompt |
| LLM produces inconsistent YAML across runs | Phase 3 revalidation reuses Phase 1 YAML; Phase 4 re-runs only when YAML is structurally broken |
| Fix for one database breaks another | Phase 3 revalidation runs ALL databases after each Phase 2 fix; regression detection immediate |
| Code change violates "no business logic in core" boundary (Section 4) | Apply Decision Test before each fix; if fails, find a more generic formulation or move fix to plugin layer |
| Doc sync forgotten | Each Phase 2 commit MUST include doc updates; `pytest tests/test_doc_sync.py` gate |
| Temporary files pollute working tree | All temp scripts use `_` prefix (gitignored); cleanup after each round |

## Section 10: Out of Scope (Deferred)

- R8 PostgreSQL runtime validation → separate follow-up spec after Docker/PG ready
- Performance benchmarking → not part of correctness validation
- New database creation → covered by predecessor spec (R8 already created)
- Database SQL file modifications → covered by predecessor spec (already done)

## Section 11: Success Definition

The project is considered successfully validated when:

1. All 7 SQLite databases (R1-R7) pass 5-dimension verification with the same
   project code commit on `feat/contract-driven-self-healing` branch
2. All Phase 2 fixes have corresponding unit tests passing
3. `ruff check`, `mypy`, `pytest` all clean
4. `pytest tests/test_doc_sync.py` passes (doc markers in sync)
5. All markdown docs updated to reflect logic changes
6. Working tree is clean (no temp files left)
7. The fixes are generic improvements (pass the Section 4 Decision Test)

After success, the user manually reviews and approves merge to `main` per
established branch strategy.
