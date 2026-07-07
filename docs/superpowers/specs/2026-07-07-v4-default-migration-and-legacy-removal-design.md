# v4 Default Migration & Legacy Removal Design

**Status:** Implemented (2026-07-07)
**Date:** 2026-07-07
**Author:** sqlseed team
**Supersedes:** Rule-based engine in `staged_analyzer.py` (final migration)
**Related:** [2026-07-05-contract-driven-self-healing-design.md](./2026-07-05-contract-driven-self-healing-design.md)
**Implementation:** [2026-07-07-v4-default-migration-and-legacy-removal.md](../plans/2026-07-07-v4-default-migration-and-legacy-removal.md)
**Compliance report:** [v4_spec_compliance_report.md](../plans/v4_spec_compliance_report.md)

---

## 1. Motivation

### 1.1 Problem Statement

The sqlseed-ai plugin currently has **two parallel validation/repair systems**:

1. **Legacy path** (default): `SchemaSemanticAnalyzer` + `Stage3Validator` with 36 patch-style rules (`_apply_rule_N_xxx`)
2. **v4 path** (opt-in via `--auto-heal`): `AutoHealOrchestrator` with 6-layer contract-driven architecture

The v4 architecture is **100% implemented** (all 6 layers + 8 defense lines have complete file structures and logic), but it is **not the default path**. This creates:

1. **Code rot** — Two parallel systems with duplicated logic, inconsistent behavior, and dead code paths
2. **Patch-style naming** — Rules use `_apply_rule_N_xxx` numbering instead of semantic names; new rules (#31-#36) continue accumulating patch debt
3. **Implicit ordering** — Rule execution order maintained via comments, not explicit dependency declarations
4. **Closed-set violation** — Adding a new Rule requires modifying `Stage3Validator.validate()` core code, violating the Open-Closed Principle
5. **Incomplete v4 coverage** — Rules #31-#36 (added after v4 spec was written) have no v4 mapping

### 1.2 Goals

| Requirement | How this design achieves it |
|-------------|---------------------------|
| Zero code rot | Delete all legacy code after migration; single source of truth |
| Zero dead code | `git grep` for legacy symbols returns 0 results |
| Core code stability | v4 core (validator/executor/pipeline) is a closed set; new rules only add strategies/contracts |
| Semantic naming | All rules use semantic names (`strip_invalid_date_derive_from`), not numbered patches |
| Best practices | Contract-driven + Registry + stateless strategies + topological validation |
| Long-term value | v4 is the final architecture; no future "migration off Stage3Validator" needed |

### 1.3 Design Principles

1. **Open-Closed Principle** — Core code (Registry + Validator + Executor) is closed; Rules are open for extension
2. **Zero Rot** — No transitional bridges, no deprecated flags, no dual-track systems
3. **Test-First Migration** — Each rule migration is gated by a passing unit test
4. **Loop Engineering Validation** — End-to-end ai-analyze + fill must achieve 16/16 table success
5. **Spec Compliance** — Final state matches `2026-07-05-contract-driven-self-healing-design.md`

---

## 2. Current State Assessment

### 2.1 v4 Implementation Status (Verified 2026-07-07)

| Layer | Module | Files | Status |
|-------|--------|-------|--------|
| Layer 1 | `contracts/` | `matrix.py`, `builtin_violations.py`, `registry.py` | ✅ 100% |
| Layer 2 | `validator/` | `main.py`, `single_column.py`, `cross_column.py`, `composite_fk.py`, `dialect_parser.py`, `schema_snapshot.py`, `shadow_fk_scan.py`, `models.py` | ✅ 100% |
| Layer 3 | `repair/` | `executor.py`, `pipeline.py`, `strategies.py` (13 strategies), `models.py` | ✅ 100% |
| Layer 4 | `healer/` | `coordinator.py`, `llm_healer.py`, `degrader.py`, `diff_learner.py`, `oscillation.py`, `post_repair.py`, `subgraph.py`, `models.py` | ✅ 100% |
| Orchestration | `auto_heal/` | `orchestrator.py`, `time_budget.py` | ✅ 100% |

**v4 is fully implemented and functional.** The `AutoHealOrchestrator.run()` method complete chains: snapshot → validate → repair → heal → write.

### 2.2 Legacy System Status

| Component | Location | Status |
|-----------|----------|--------|
| `Stage3Validator` | `staged_analyzer.py` (~5000+ lines) | Active, default path |
| `apply_auto_fix_rules_1_13()` | `schema_analyzer.py` | Active, called by legacy path |
| `LegacyRuleBridge` | `repair/legacy_bridge.py` | Maps #14-#30 to v4 strategy names (16 rules) |
| Rules #31-#36 | `staged_analyzer.py` | No v4 mapping, patch-style only |

### 2.3 Coverage Gap

The v4 `repair/strategies.py` has 13 stateless strategy functions. The legacy `Stage3Validator` has 36 rules. The coverage gap must be determined empirically (Phase 1) and closed (Phase 2).

**Known uncovered rules** (no v4 strategy mapping in `LegacyRuleBridge`):
- #15 `bound_regex` (Legacy-only)
- #17 `handle_boolean_derive` (Legacy-only)
- #18 `limit_future_year` (Legacy-only)
- #23 `upgrade_phone_to_pattern` (Legacy-only)
- #25 `downgrade_text_to_string` (Legacy-only)
- #27 `infer_derive_from_check` (Legacy-only)
- #31 `strip_composite_unique`
- #32 `detect_boolean_enum`
- #33 `detect_text_enum`
- #34 `cross_column_numeric_check`
- #35 `strip_generator_from_derive_from`
- #36 `strip_invalid_date_derive_from`

---

## 3. Architecture: Final Target State

```
plugins/sqlseed-ai/src/sqlseed_ai/
├── contracts/                    # Layer 1: Contract Matrix (closed set)
│   ├── matrix.py                 # ContractViolation + ContractResolver
│   ├── builtin_violations.py     # Built-in violations (~50-100 entries)
│   └── registry.py               # Learned contracts registry (JSON-persisted)
├── validator/                    # Layer 2: Fast Validator (closed set)
│   ├── main.py                   # FastValidator orchestration
│   ├── single_column.py          # Single-column contract checks
│   ├── cross_column.py           # Cross-column constraint checks
│   ├── composite_fk.py           # Composite FK coordination
│   ├── dialect_parser.py         # Dialect-aware error parser
│   ├── schema_snapshot.py        # Schema static snapshot
│   ├── shadow_fk_scan.py         # Shadow FK scanner
│   └── models.py                 # Validator data models
├── repair/                       # Layer 3: Repair Engine (closed set + open strategies)
│   ├── executor.py               # RepairExecutor (closed)
│   ├── pipeline.py               # Repair pipeline (closed)
│   ├── strategies.py             # Stateless strategies (OPEN — add rules here)
│   └── models.py                 # Repair data models
├── healer/                       # Layer 4: LLM Healer (closed set)
│   ├── coordinator.py            # Reconcile loop
│   ├── llm_healer.py             # LLM regeneration
│   ├── degrader.py               # Progressive degrade
│   ├── diff_learner.py           # Diff learning → registry
│   ├── oscillation.py            # Oscillation detection
│   ├── post_repair.py            # Post-repair alignment
│   ├── subgraph.py               # Dependency subgraph splitting
│   └── models.py                 # Healer data models
├── auto_heal/                    # Orchestration (closed set)
│   ├── orchestrator.py           # AutoHealOrchestrator (main entry)
│   └── time_budget.py            # TimeBudgetController
├── analyzer/                     # LLM calling layer (existing)
│   ├── _caller.py
│   ├── _streaming.py
│   ├── _tool_calling.py
│   ├── _context.py
│   └── _json_parser.py
├── cli/
│   └── ai_commands.py            # ai-analyze command (default: v4)
├── _stage_prompts.py             # Stage prompts (existing)
├── config.py                     # AIConfig
└── ...                           # Other existing modules

DELETED after Phase 4:
  ❌ staged_analyzer.py
  ❌ schema_analyzer.py (apply_auto_fix_rules_1_13)
  ❌ repair/legacy_bridge.py
```

### 3.1 Core Code vs Extensible Code

| Classification | Files | Change Frequency |
|----------------|-------|------------------|
| **Core (closed set)** | `contracts/matrix.py`, `validator/*`, `repair/executor.py`, `repair/pipeline.py`, `healer/*`, `auto_heal/*` | Rarely changed (Open-Closed Principle) |
| **Extensible (open set)** | `contracts/builtin_violations.py`, `repair/strategies.py` | Changed when adding new rules |
| **LLM layer** | `analyzer/*`, `_stage_prompts.py` | Independent evolution |

---

## 4. Migration Plan: 5 Phases

### Phase 1: Coverage Validation

**Goal:** Determine which of the 36 legacy rules are already covered by v4 and which need migration.

**Strategy:** Dual-track comparison testing on the same schema.

**Test Schemas:**
- `trading_platform.db` — 16 tables with CHECK + FK + composite UNIQUE + multi-CHECK chains + date derive_from (from Loop Engineering Phase 7-8)
- Existing v4 test schemas in `plugins/sqlseed-ai/tests/`
- New edge-case schemas as needed

**Steps:**
1. Run Stage3Validator on `trading_platform.db` → record output YAML (baseline)
2. Run v4 `AutoHealOrchestrator` on same schema → record output YAML
3. Diff the two YAMLs
4. For each difference, classify:
   - v4 output correct → Rule covered ✅
   - v4 output wrong/missing → Rule needs migration ❌
   - Both correct but different → Acceptable variant ⚠️

**Output:**
- Coverage gap matrix (36 rules × v4 strategy × status)
- Migration priority list (sorted by complexity and frequency)

**Exit Criteria:**
- Every rule classified as ✅ or ❌
- Migration scope determined

---

### Phase 2: Uncovered Rule Migration

**Goal:** Migrate all uncovered rules to v4 framework.

**Migration Targets:**

| Rule Type | Target Location | Example |
|-----------|-----------------|---------|
| Repair strategy (how to fix) | `repair/strategies.py` | `strip_invalid_date_derive_from()` |
| Violation definition (what's wrong) | `contracts/builtin_violations.py` | `ContractViolation(generator=..., fix_strategy="strip_invalid_date_derive_from")` |
| Validation logic (constraint check) | `validator/single_column.py` or `cross_column.py` | Cross-column CHECK verification |
| LLM prompt guidance | `_stage_prompts.py` or `healer/` prompts | Stage 2/3 prompt updates |

**Migration Principles:**
1. **Semantic naming** — New strategies use semantic names, no rule numbers
2. **Stateless** — Strategies are pure functions, no instance state
3. **Contract-driven** — Prefer declaring violations in the contract matrix over hardcoding detection
4. **Test-first** — Write unit test before migration; test must pass on legacy behavior before new code is accepted

**Migration Order (by dependency):**

```
Phase 2a: Simple strategies (no dependencies)
  - bound_regex (#15)
  - limit_future_year (#18)
  - downgrade_text_to_string (#25)
  - upgrade_phone_to_pattern (#23)

Phase 2b: Composite strategies (with dependencies)
  - handle_boolean_derive (#17) — depends on #32 boolean enum detection
  - infer_derive_from_check (#27) — depends on #22 date range isolation

Phase 2c: New rules (#31-#36)
  - strip_composite_unique (#31)
  - detect_boolean_enum (#32)
  - detect_text_enum (#33)
  - cross_column_numeric_check (#34)
  - strip_generator_from_derive_from (#35)
  - strip_invalid_date_derive_from (#36)
```

**Per-Rule Migration Flow:**
1. Read `Stage3Validator._apply_rule_N_xxx` full logic
2. Write unit test based on existing `trading_platform_v7.yaml` behavior
3. Implement in v4:
   - Repair logic → `repair/strategies.py` new function
   - Detection logic → `validator/` new method
   - Violation definition → `contracts/builtin_violations.py` new `ContractViolation`
4. Run unit test, confirm pass
5. Mark rule as ✅ in coverage matrix

**Exit Criteria:**
- Coverage gap matrix all ✅
- Each migrated rule has a passing unit test
- `repair/strategies.py` has ~10-15 new stateless functions
- `contracts/builtin_violations.py` has ~5-10 new `ContractViolation` entries

---

### Phase 3: Default Path Switch

**Goal:** Make v4 `AutoHealOrchestrator` the default path for `ai-analyze`.

**CLI Change:**
```python
# plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py

# Before (legacy default)
@ai.command("ai-analyze")
def ai_analyze(...):
    analyzer = SchemaSemanticAnalyzer(...)
    result = analyzer.analyze(...)

# After (v4 default)
@ai.command("ai-analyze")
def ai_analyze(...):
    orchestrator = AutoHealOrchestrator(...)
    result = orchestrator.run(...)
```

**No transitional flag.** Per the "zero rot" requirement, there is no `--legacy-staged` flag. If v4 passes all Phase 2 validation, the switch is direct.

**Pre-Switch Validation Checklist:**
1. Phase 2 coverage matrix all ✅
2. `trading_platform.db` end-to-end: v4 ai-analyze → fill → 16/16 tables succeed
3. Existing v4 tests pass: `pytest plugins/sqlseed-ai/tests/test_validator_*` + `test_repair_*` + `test_healer_*` + `test_auto_heal_*`
4. Legacy Stage3Validator test suite passes (baseline behavior)
5. Loop Engineering end-to-end: rebuild DB → v4 ai-analyze → fill → 16/16 tables succeed

**Exit Criteria:**
- `ai-analyze` defaults to `AutoHealOrchestrator`
- End-to-end test passes (16/16 tables)
- Loop Engineering convergence: 16/16

---

### Phase 4: Legacy Removal

**Goal:** Delete all legacy code and tests, achieving zero dead code.

**Source Code Deletion:**

| File | Action | Reason |
|------|--------|--------|
| `staged_analyzer.py` | Delete entirely | Stage3Validator superseded by v4 |
| `schema_analyzer.py` | Delete `apply_auto_fix_rules_1_13()` | Fix 1-13 logic migrated to v4 |
| `schema_analyzer.py` | Delete entire file if no other content | Confirm no other exports first |
| `repair/legacy_bridge.py` | Delete entirely | LegacyRuleBridge no longer needed |

**Test File Cleanup:**

| Test File | Action | Verification |
|-----------|--------|--------------|
| `tests/test_staged_analyzer.py` | Delete | Confirm v4 tests cover equivalent scenarios |
| `tests/test_schema_analyzer.py` | Delete (if only tests Fix 1-13) | Confirm v4 tests cover |
| `tests/test_legacy_bridge.py` (if exists) | Delete | Bridge removed, test meaningless |
| `tests/test_*_rule_N_*.py` (if exists) | Delete or rename | Numbered naming deprecated |
| `tests/conftest.py` Stage3Validator fixtures | Remove | Confirm v4 tests don't depend on them |

**Pre-Deletion Verification:**
```bash
# Step 1: Confirm no imports of legacy modules
git grep "from sqlseed_ai.staged_analyzer import" || echo "CLEAN"
git grep "from sqlseed_ai.schema_analyzer import apply_auto_fix_rules_1_13" || echo "CLEAN"
git grep "from sqlseed_ai.repair.legacy_bridge import" || echo "CLEAN"

# Step 2: Run full test suite (no import errors)
pytest plugins/sqlseed-ai/tests/

# Step 3: Lint and type check (no unresolved references)
ruff check plugins/sqlseed-ai/
mypy plugins/sqlseed-ai/

# Step 4: End-to-end functional test
sqlseed ai-analyze test.db --config out.yaml
sqlseed fill test.db --config out.yaml
```

**Documentation Cleanup:**

| Document | Action |
|----------|--------|
| `CLAUDE.md` Stage3Validator sections | Update to v4 description |
| `AGENTS.md` Rule tables | Update to v4 architecture |
| `docs/architecture.md` | Update to v4 architecture |
| `2026-07-05-contract-driven-self-healing-design.md` | Mark as "Implemented" |
| Any doc referencing `Rule #N` | Update to semantic name or remove |

**Exit Criteria:**
- `git grep "Stage3Validator"` returns 0 results
- `git grep "apply_auto_fix_rules_1_13"` returns 0 results
- `git grep "LegacyRuleBridge"` returns 0 results
- `git grep "_apply_rule_"` returns 0 results
- `git grep "staged_analyzer"` returns 0 results (except this spec doc, historical reference)
- Full test suite passes
- ruff + mypy pass

---

### Phase 5: Spec Validation & Loop Engineering

**Goal:** Verify implementation matches v4 spec and achieves zero rot.

#### A. v4 Spec Compliance Check

Cross-reference `2026-07-05-contract-driven-self-healing-design.md` item by item:

| Spec Item | Verification Method | Pass Criteria |
|-----------|---------------------|---------------|
| 6-layer architecture | Check directories exist | All present |
| 8 defense lines | Check each defense has implementation | All implemented |
| Layer 1 contract matrix | `contracts/matrix.py` + `builtin_violations.py` | Complete |
| Layer 2 fast validator | `validator/main.py` + single/cross column | Complete |
| Layer 3 repair engine | `repair/executor.py` + `strategies.py` | All 36 rule scenarios covered |
| Layer 4 LLM healer | `healer/coordinator.py` + `llm_healer.py` | Complete |
| TimeBudgetController | `auto_heal/time_budget.py` | Complete |
| Learned Registry | `contracts/registry.py` + JSON persistence | Complete |

#### B. Zero Dead Code Verification

```bash
# All must return 0 results
git grep "Stage3Validator" || echo "CLEAN"
git grep "apply_auto_fix_rules_1_13" || echo "CLEAN"
git grep "LegacyRuleBridge" || echo "CLEAN"
git grep "_apply_rule_" || echo "CLEAN"
git grep "Rule #[0-9]" || echo "CLEAN"
git grep "Fix [0-9]" || echo "CLEAN"
git grep "legacy_bridge" || echo "CLEAN"
git grep "staged_analyzer" || echo "CLEAN"
```

#### C. Loop Engineering End-to-End

```
1. Rebuild trading_platform.db (16 tables: CHECK + FK + composite UNIQUE + date chains)
2. Run v4 ai-analyze (default path, no --legacy-staged)
3. Run fill --config
4. Verify 16/16 tables succeed, 16000 rows
5. Verify all CHECK constraints satisfied
6. Compare against Round 7 baseline behavior, confirm no regression
```

#### D. Full Test Suite

```bash
# Full test suite
pytest

# Per-module
pytest plugins/sqlseed-ai/tests/test_validator_*
pytest plugins/sqlseed-ai/tests/test_repair_*
pytest plugins/sqlseed-ai/tests/test_healer_*
pytest plugins/sqlseed-ai/tests/test_auto_heal_*
pytest plugins/sqlseed-ai/tests/test_contracts_*

# Core + other plugins unaffected
pytest tests/
pytest plugins/sqlseed-cli/tests/
pytest plugins/mcp-server-sqlseed/tests/
```

#### E. Documentation Sync

```bash
git grep -l "Stage3Validator" docs/ README.md CLAUDE.md AGENTS.md || echo "CLEAN"
git grep -l "Rule #[0-9]" docs/ README.md CLAUDE.md AGENTS.md || echo "CLEAN"
pytest tests/test_doc_sync.py
```

**Exit Criteria:**
- v4 Spec validation report (all items ✅)
- Zero dead code proof (all grep CLEAN)
- Loop Engineering convergence (16/16)
- Full test suite passes
- Documentation sync passes

---

## 5. Risk Assessment & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| v4 strategy coverage gaps > expected | Phase 2 scope expands | Phase 1 empirically determines scope; prioritize by frequency |
| v4 behavior differs from legacy in subtle ways | Fill failures on edge cases | Loop Engineering end-to-end validation in Phase 3 + Phase 5 |
| LLM Healer performance regression | ai-analyze slower than legacy | TimeBudgetController (default 300s) + deterministic degrade |
| Test coverage insufficient | Migration introduces regressions | Test-first migration; each rule gated by unit test |
| Breaking change for users | Existing workflows break | v4 is already opt-in via `--auto-heal`; switch makes it default but behavior should be equivalent |
| Documentation drift | Confusion for new contributors | Phase 4 includes doc cleanup; `test_doc_sync.py` verifies |

---

## 6. Workload Estimate

| Phase | Effort | Description |
|-------|--------|-------------|
| P1 Coverage Validation | 1-2 days | Run dual-track tests, analyze gaps |
| P2 Rule Migration | 3-5 days | Depends on gap size (~10-20 rules to migrate) |
| P3 Default Switch | 1 day | CLI change + end-to-end validation |
| P4 Legacy Removal | 0.5 days | Mechanical deletion + test cleanup |
| P5 Spec Validation | 1 day | Spec cross-reference + Loop Engineering |
| **Total** | **6-9 days** | Far less than "build v4 from scratch" since v4 is already complete |

---

## 7. Success Criteria

The migration is complete when **all** of the following are true:

1. ✅ `ai-analyze` defaults to v4 `AutoHealOrchestrator`
2. ✅ `staged_analyzer.py`, `schema_analyzer.py::apply_auto_fix_rules_1_13`, `repair/legacy_bridge.py` are deleted
3. ✅ All legacy test files are deleted
4. ✅ `git grep` for all legacy symbols returns 0 results
5. ✅ All 36 rule scenarios are covered by v4 (coverage matrix all ✅)
6. ✅ Loop Engineering: trading_platform.db → v4 ai-analyze → fill → 16/16 tables succeed
7. ✅ Full test suite passes (`pytest`)
8. ✅ ruff + mypy pass
9. ✅ v4 spec compliance check passes
10. ✅ Documentation updated and `test_doc_sync.py` passes

---

## 8. Out of Scope

- **SP4 (Layer 4 LLM Healer enhancements)**: The healer is already implemented. Enhancements like new prompt strategies or model-specific tuning are independent of this migration.
- **Performance optimization**: Not a goal; v4 performance is validated in Phase 3.
- **New rule addition**: This migration covers existing 36 rules. New rules added after migration should follow the v4 pattern (add to `strategies.py` + `builtin_violations.py`).
- **PostgreSQL-specific testing**: Loop Engineering uses SQLite. PG integration is verified by existing `test_pg_integration.py`.

---

## 9. References

- [v4 Contract-Driven Self-Healing Design](./2026-07-05-contract-driven-self-healing-design.md) — The v4 architecture spec
- [Loop Engineering Methodology](../../../user_profile.md) — Iterative fix methodology
- `plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py` — v4 entry point
- `plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py` — Legacy (to be deleted)
- `plugins/sqlseed-ai/src/sqlseed_ai/repair/legacy_bridge.py` — Legacy bridge (to be deleted)
