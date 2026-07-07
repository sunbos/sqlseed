# v4 Spec Compliance Report

**Date:** 2026-07-07
**Validator:** assistant (GLM-5.2)
**Spec:** [2026-07-05-contract-driven-self-healing-design.md](./specs/2026-07-05-contract-driven-self-healing-design.md)
**Implementation plan:** [2026-07-07-v4-default-migration-and-legacy-removal.md](./plans/2026-07-07-v4-default-migration-and-legacy-removal.md)

## Compliance Matrix

| Spec Item | Verification Method | Status | Notes |
|-----------|---------------------|--------|-------|
| 6-layer architecture | `LS plugins/sqlseed-ai/src/sqlseed_ai/{contracts,validator,repair,healer,auto_heal,analyzer}/` | ✅ | All 6 directories exist with `__init__.py` |
| 8 defense lines | See Defense Lines Verification table below | ✅ | All 8 defenses have implementation |
| Layer 1 contract matrix | `contracts/matrix.py` (`ContractViolation`, `ContractResolver`) + `builtin_violations.py` | ✅ | 23 builtin violations; `ContractResolver` with specificity-priority matching |
| Layer 2 fast validator | `validator/main.py` (`FastValidator`) + `single_column.py` + `cross_column.py` | ✅ | Orchestrates 5 components (2a, 2b, Defense 3, Defense 5, Shadow FK scan) |
| Layer 3 repair engine | `repair/executor.py` + `strategies.py` (`REPAIR_STRATEGIES`) + `pipeline.py` | ✅ | 25 stateless strategies; all 36 legacy rule scenarios covered (see coverage matrix) |
| Layer 4 LLM healer | `healer/coordinator.py` (`Layer4Coordinator`) + `llm_healer.py` | ✅ | Includes oscillation detection, progressive degrade, subgraph splitting, diff learning |
| TimeBudgetController | `auto_heal/time_budget.py` | ✅ | Default 300s budget; per-table dynamic allocation |
| Learned Registry | `contracts/registry.py` (`LearnedContractsRegistry`) with JSON persistence | ✅ | Defense 1 sandbox (SAFE_FIX_STRATEGIES, 17 entries) + Defense 7 RCE filter (FORBIDDEN_PERSIST_KEYS, 16 keys) |
| AutoHealOrchestrator | `auto_heal/orchestrator.py` | ✅ | Top-level entry point for `ai-suggest --auto-heal`; pipeline: snapshot → subgraph → per-subgraph (validate→repair→heal) → post-repair → optimistic lock → YAML |
| Legacy code removed | `git grep` for `staged_analyzer`, `schema_analyzer`, `Stage3Validator`, etc. | ✅ | 6 source files + 8 test files deleted; only intentional migration-history comments remain |
| `ai-suggest` defaults to v4 | `cli/ai_commands.py` no `--staged-pipeline` flag; `AIConfig` no `use_staged_pipeline` field | ✅ | Default path is v4 AutoHealOrchestrator |

## Defense Lines Verification

| Defense | Implementation Location | Status | Evidence |
|---------|------------------------|--------|----------|
| Defense 1: Safety sandbox | `contracts/registry.py` `SAFE_FIX_STRATEGIES` | ✅ | `frozenset` of 17 safe strategy names; `add()` refuses anything outside the set |
| Defense 2: Tarjan SCC | `healer/subgraph.py` `TarjanSCC` class | ✅ | Iterative Tarjan algorithm (`find_sccs` method); avoids recursion-limit issues |
| Defense 3: Dialect parser | `validator/dialect_parser.py` `DialectErrorParser` | ✅ | SQLite + PostgreSQL parsing branches; normalizes DBAPI exceptions to `ViolationReport` |
| Defense 4: Cascade degrade | `healer/degrader.py` `ProgressiveDegrader` | ✅ | `_cascade_degrade` method; cascades to derive_from dependents + composite FK groups |
| Defense 5: Composite FK | `validator/composite_fk.py` `CompositeFKCoordinator` | ✅ | Multi-column FK coordination at Layer 2 + Layer 4 |
| Defense 6: Megacluster | `healer/subgraph.py` `SubgraphSplitter` | ✅ | Greedy edge removal until SCC splits into chunks ≤ `max_scc_size` |
| Defense 7: RCE interception | `contracts/registry.py` `FORBIDDEN_PERSIST_KEYS` | ✅ | `frozenset` of 16 forbidden keys (custom_function, eval, exec, lambda, etc.); `add()` refuses persistence |
| Defense 8: Schema snapshot | `validator/schema_snapshot.py` `SchemaSnapshot` | ✅ | `schema_hash` computed at startup; `write_yaml_with_optimistic_lock` re-checks before write |

## Layer Coverage Details

### Layer 1 — `contracts/`
- `matrix.py`: `ViolationKind` enum (CRASH, SEMANTIC_ERROR, UNIQUE_UNSATISFIABLE, CONDITIONAL), `ContractViolation` dataclass, `ContractResolver` with specificity-priority matching (1=exact, 2=partial wildcard, 3=full wildcard)
- `builtin_violations.py`: 23 builtin `ContractViolation` entries covering type compatibility (Rule #30), UNIQUE cardinality (Rule #24), and Phase 2 migrations (Rules #15, #17, #18, #23, #25, #27, #31-#36)
- `registry.py`: `LearnedContractsRegistry` with JSON persistence, `SAFE_FIX_STRATEGIES` (Defense 1), `FORBIDDEN_PERSIST_KEYS` (Defense 7), `filter_by_schema_hash` (Defense 8)

### Layer 2 — `validator/`
- `main.py`: `FastValidator` orchestrating 5 components
- `single_column.py` (2a): per-column contract + cardinality check
- `cross_column.py` (2b): FK integrity + derive_from DAG cycle detection
- `dialect_parser.py` (Defense 3): SQLite/PostgreSQL error normalization
- `composite_fk.py` (Defense 5): multi-column FK coordination
- `shadow_fk_scan.py`: SQLite FK violation column localization (Section 14.3)
- `schema_snapshot.py` (Defense 8): `schema_hash` + optimistic lock
- `models.py`: `ConstraintType`, `ViolationReport`, `ValidationResult`

### Layer 3 — `repair/`
- `strategies.py`: 25 stateless repair strategies in `REPAIR_STRATEGIES` dict. `_GENERATOR_PARAM_WHITELIST` expanded to 36 entries (Phase 4 Task 4.1 fix). Key strategies: `normalize_params` (Rule #14), `coerce_float_to_int` (Rule #26), `strip_generator_from_derive_from` (Rule #35), `strip_invalid_date_derive_from` (Rule #36), `infer_derive_from_check` (CHECK chain mirroring)
- `executor.py`: applies strategies by `fix_hint` dispatch
- `pipeline.py`: chains strategies

### Layer 4 — `healer/`
- `coordinator.py`: `Layer4Coordinator` entry point
- `llm_healer.py`: LLM regeneration with violation context
- `oscillation.py`: repeated failure detection (same_error_count reset on type change)
- `degrader.py` (Defense 4): `ProgressiveDegrader` with normal → compact → ultra-compact context fallback
- `subgraph.py` (Defenses 2 + 6): `TarjanSCC` + `SubgraphSplitter`
- `post_repair.py`: `BrokenEdgeAligner` for broken FK edges
- `diff_learner.py`: persists learned violations back to Layer 1 (with Defense 7 interception)

### Layer 5 — `auto_heal/`
- `orchestrator.py`: `AutoHealOrchestrator` — top-level entry point for `ai-suggest --auto-heal`
- `time_budget.py`: `TimeBudgetController` (default 300s)

### Layer 6 — `analyzer/`
- LLM table-level analysis: `_caller.py`, `_streaming.py`, `_tool_calling.py` (protocol-based: gemma4/openai/none), `_context.py`, `_json_parser.py`
- Used by the non-auto-heal `ai-suggest` path

## Legacy Migration Coverage

All 36 legacy `Stage3Validator` rule scenarios are covered by v4. See [`v4_coverage_matrix.md`](./plans/v4_coverage_matrix.md) for the full rule-by-rule mapping. Notable migrations:

| Legacy Rule | v4 Strategy | Verification |
|-------------|-------------|--------------|
| Rule #14 (param whitelist stripping) | `normalize_params` | ✅ Refiner delegates to `REPAIR_STRATEGIES["normalize_params"]`; 36-entry whitelist |
| Rule #22 (date year range) | Deferred `_has_date_year_range` check | ✅ Runs after derive_from processing |
| Rule #26 (random_float → random_int) | `coerce_float_to_int` | ✅ INTEGER column coercion |
| Rule #35 (strip non-timedelta derive_from) | `strip_generator_from_derive_from` | ✅ Date column cleanup |
| Rule #36 (date generator coercion) | `strip_invalid_date_derive_from` + `_ensure_date_generator_for_date_column` | ✅ Wrong generator → datetime conversion |

## Test Verification

| Test Suite | Count | Status |
|------------|-------|--------|
| Full test suite (excluding integration/benchmarks) | 1954 passed, 3 skipped | ✅ |
| Architecture guards (`test_architecture.py`) | 14 passed | ✅ |
| Doc sync (`test_doc_sync.py`) | 17 passed | ✅ |
| Refiner tests (root + plugin) | 71 passed | ✅ |
| ruff check | All checks passed | ✅ |
| mypy | Success: no issues found in 116 source files | ✅ |

## Conclusion

**Overall: ✅ PASS**

The v4 contract-driven self-healing architecture is fully implemented and complies with the spec. All 6 layers, 8 defense lines, and 25 repair strategies are in place. All 36 legacy `Stage3Validator` rule scenarios are covered by v4 strategies. The legacy code has been completely removed (zero dead code verified). The full test suite (1954 tests), ruff, mypy, architecture guards, and doc sync all pass.

The implementation is ready for user review and merge confirmation.
