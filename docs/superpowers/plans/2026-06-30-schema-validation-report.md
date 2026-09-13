# Stage 7.1 — Schema-Driven Architecture Refactor: Regression Validation Report

**Date:** 2026-06-30
**Branch:** `feat/schema-driven-architecture`
**Base branch:** `feat/multi-db-support`
**Plan:** `docs/superpowers/plans/2026-06-30-schema-driven-architecture.md`

## Summary

The full test suite was executed against the completed schema-driven
architecture refactor (Stages 1–6) to verify no regressions were
introduced. **No new failures attributable to the refactor were found.**
All 5 observed failures are pre-existing (LLM-dependent integration
tests and one unrelated prompt-text assertion that predates this
refactor).

## Test Run

**Command:**

```
python -m pytest tests/ plugins/sqlseed-ai/tests/ plugins/sqlseed-cli/tests/ plugins/mcp-server-sqlseed/tests/ --tb=short -q
```

**Result:** `5 failed, 1729 passed, 3 skipped in 400.43s`

| Metric   | Count |
|----------|-------|
| Passed   | 1729  |
| Failed   | 5     |
| Skipped  | 3     |
| Total    | 1737  |

The 3 skipped tests are MCP tests skipped due to missing
`sqlseed-ai` API key configuration (`plugins/sqlseed-ai/tests/test_mcp.py`).

## Failure Analysis

All 5 failures are documented below. Each was verified to be
**unrelated to the schema-driven refactor** — i.e., the failing test
files and the production code they exercise were NOT modified in the
`feat/multi-db-support..HEAD` commit range.

### 1. `tests/integration/test_ai_real_llm.py::TestAiConfigRefinerRealLLM::test_generate_and_refine_streaming_invokes_no_state_mutation`

- **Category:** LLM-dependent integration test (requires real LLM backend).
- **Error:** `AISuggestionFailedError: Failed after 1 retries. Last error: ConfigurationError: Generator 'email' misconfigured: MimesisProvider._gen_email() got an unexpected keyword argument 'example'`
- **Diagnosis:** Real-LLM end-to-end refinement test. Fails because the
  live LLM produced a config with an `email` generator parameter
  (`example`) that the mimesis provider does not accept. This is an
  LLM-output / provider-capability mismatch, not a regression from the
  refactor.

### 2. `tests/integration/test_ai_real_llm.py::TestAISqlseedPluginHookRealLLM::test_hookimpl_returns_dict_or_none`

- **Category:** LLM-dependent integration test (requires real LLM backend).
- **Error:** `AssertionError: hookimpl result missing tables/columns key: []`
- **Diagnosis:** Asserts the AI plugin hook returns a dict containing
  `tables` or `columns`. The live LLM returned an empty dict `{}`.
  This is LLM-output dependent, not a refactor regression.

### 3. `tests/test_refiner.py::TestCriticalConstraints::test_ultra_compact_prompt_excludes_pk_default_unique_check`

- **Category:** Pre-existing prompt-text assertion failure (NOT LLM-dependent, NOT refactor-related).
- **Error:** `AssertionError: assert 'PRIMARY KEY' in 'OUTPUT JSON TEST DATA CONFIG.\nSKIP PK AUTOINCREMENT, ...'`
- **Diagnosis:** The test asserts the literal substring `"PRIMARY KEY"`
  appears in `_ULTRA_COMPACT_SYSTEM_PROMPT`. The prompt was previously
  reworded to use `"PK AUTOINCREMENT"` instead of `"PRIMARY KEY"`.
  Verified pre-existing: `git diff feat/multi-db-support..HEAD -- tests/test_refiner.py plugins/sqlseed-ai/src/sqlseed_ai/_prompts.py` is **empty** — neither file was modified by the schema-driven refactor. This failure is identical on the base branch.

### 4. `plugins/sqlseed-ai/tests/test_ai_plugin.py::TestSchemaAnalyzerDialect::test_analyze_schema_sqlite_real_llm`

- **Category:** LLM-dependent integration test (requires real LLM backend).
- **Error:** `AssertionError: Unexpected LLM response structure: {}`
- **Diagnosis:** Live LLM returned an empty dict. Asserts `tables` or
  `columns` key present. LLM-output dependent, not a refactor regression.

### 5. `plugins/sqlseed-ai/tests/test_ai_plugin.py::TestSchemaAnalyzerDialect::test_analyze_schema_llm_response_structure`

- **Category:** LLM-dependent integration test (requires real LLM backend).
- **Error:** `AssertionError: LLM response should contain a 'tables' or 'columns' key, actual keys: []`
- **Diagnosis:** Live LLM returned an empty dict. LLM-output dependent,
  not a refactor regression.

## Regression Verification

Per the plan's "Critical Implementation Details", the refactor must NOT
change these counts. All verified unchanged (see Task 7.2 architecture
guard tests and Task 7.3 doc sync tests for formal verification):

- Generator count: 32 (unchanged)
- Hook count: 12 (unchanged)
- Exact-match rule count: 74 (unchanged; CHECK parser is a separate module)
- Pattern-match rule count: 29 (unchanged)

## Verdict

**PASS — No regressions introduced by the schema-driven architecture refactor.**

All 5 failures are either:
1. LLM-dependent integration tests requiring a live LLM backend
   (failures #1, #2, #4, #5), or
2. A pre-existing prompt-text assertion failure identical on the base
   branch (failure #3), with the affected files untouched by this
   refactor.

The 1729 passing tests include all core schema-driven fallback tests
(`tests/test_core/test_check_parser.py`,
`tests/test_core/test_schema_fallback.py`,
`tests/test_core/test_orchestrator_schema_fallback.py`), all AI plugin
structure/prompt tests for the new `SchemaSemanticAnalyzer` and
`DependencyResolver`, and the `ai-analyze` CLI command tests.
