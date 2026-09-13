# Core bounded review: main to candidate

Reviewed base `976b605dac47bd6d61cfcae4ff6c7a00fa0352a5` against candidate `4ba5d08364cb85f44593c57271d339d61d5bf1f9` (working HEAD). Repository source was not changed. Existing user changes were preserved.

## Confirmed findings

1. **P1 — JSON columns silently receive double-encoded strings.** `src/sqlseed/database/sqlalchemy_adapter.py:194-204` passes serialized JSON generator output directly to SQLAlchemy's typed JSON INSERT. `src/sqlseed/generators/_json_helpers.py:35` already serializes its result with `json.dumps`. A SQLite `events(id INTEGER PRIMARY KEY, payload JSON NOT NULL)` and the explicit `json` generator with object schema `{n: integer}` reproduces this with three rows and seed 42. Main stores JSON objects (`json_type = object`) and `json_extract(payload, '$.n')` returns 670487, 116739, 26225. Candidate reports count 3 and no errors but stores JSON string scalars (`json_type = text`), so all three JSON path queries return NULL. This is a true working-main regression, not a newly unsupported schema. Minimum repair: reconcile the JSON generator's serialized-string contract with the SQLAlchemy JSON/JSONB binding boundary, preserving correct object/array/scalar semantics; verify persisted DB JSON type and path extraction, not just generator strings or inserted count.

2. **P2 — SQLite DATE string configurations stop working.** `src/sqlseed/database/sqlalchemy_adapter.py:198-204`, with the typed-column exclusion at `:63-68`, does not normalize existing ISO date strings before SQLAlchemy's Date bind processor. A `holiday DATE NOT NULL` with `choice` values `['2026-01-01', '2026-12-25']` inserts three rows on main. Candidate inserts zero and returns `SQLite Date type only accepts Python date objects as input`. Minimum repair: preserve valid existing date/time string configuration support at the typed adapter boundary, with actual SQLite round-trip coverage. This is another working-main regression.

3. **P2 — Self-FK postprocessing treats the first composite-PK member as a unique row identifier.** `src/sqlseed/core/orchestrator/_generation.py:435-437` picks `pk_cols[0]`, and `:515` / `:523` update on that member only. For `(tenant, slot)` composite PK with repeated tenant, unique code, and nullable self-FK `parent_code REFERENCES nodes(code)`, seed 42 / count 20 generates twenty rows, then every row is assigned the same parent code; one row points to itself and the result has no errors. Adding `CHECK(parent_code != code)` produces a post-insert CHECK failure after all twenty generated rows were committed. Minimum repair: use the complete row key for ordering and UPDATE, or explicitly exclude this schema from automatic postprocessing until supported. Do not reject the original valid nullable data unnecessarily. Two-pass postprocessing was introduced in `e496a1f` (2026-07-11).

4. **P2 — Self-FK postprocessing ignores UNIQUE constraints.** `src/sqlseed/core/orchestrator/_generation.py:503-507` samples prior targets with replacement, then `:520-525` writes them without uniqueness-aware selection. `nodes(id INTEGER PRIMARY KEY, parent_id INTEGER UNIQUE REFERENCES nodes(id))`, seed 42 / count 20, returns `UNIQUE constraint failed: nodes.parent_id` after twenty inserts and one committed parent update. Minimum repair: make target selection honor all applicable uniqueness constraints, or leave valid NULLs when the automatic pass cannot safely construct the relation. Verify retained rows and partial updates on failure.

Findings 3 and 4 are defects in new functionality, not cases that old main handled successfully: the exact zero-config self-FK probe fails on old main earlier, with FOREIGN KEY (single PK case) or NOT NULL (integer composite PK case), leaving zero rows. Candidate improves initial generation but its new postpass is incomplete. This distinction is material to the net-improvement assessment.

## Reproduction and evidence

Python: `/tmp/sqlseed-codeflow-venv/bin/python` (3.11.15), SQLAlchemy 2.0.52. Source locations are printed in each probe output. Baseline source was exported using git archive into `/tmp/sqlseed-core-review-main-976b605/src`; candidate uses repository `src/` at the reviewed HEAD.

Probe scripts:

- `/tmp/sqlseed-core-review-json-probe.py`
- `/tmp/sqlseed-core-review-date-probe.py`
- `/tmp/sqlseed-core-review-self-fk-probe.py`

Run each with `PYTHONPATH` set to one of the above source locations. Each script uses a real temporary SQLite database, seed 42 and the base provider; no database, mapper, or generator behavior is mocked. Both versions disable optional plugin discovery because the installed candidate AI plugin cannot import against old core. Old provider discovery still emits an irrelevant optional-AI import warning; the selected base provider runs successfully. Main uses its supported RawSQLiteAdapter fallback because optional sqlite-utils is absent. Candidate uses its production SQLAlchemyAdapter.

`manifest.json` identifies the six runs and their separate raw stdout/stderr logs. Exit zero means the probe completed, not that every fill succeeded: failures are deliberately observed through `GenerationResult.errors` and persisted data.

## Intentional compatibility changes and net assessment

- The five top-level Python entry points retain their prior arguments and add mutually exclusive URL support.
- CLI moved out of core: installation needs sqlseed-cli / the cli extra, and historical `sqlseed.cli` imports are removed. `SQLiteUtilsAdapter` and old `sqlseed.generators.stream` imports are removed; DataStream now belongs to core. These are architecture migrations, not incidental bugs.
- SQLAlchemy, Faker and sqlglot are required core dependencies; SQLite-utils is removed, and tqdm's extra is renamed to notebook. Configuration `log_level` is retained but deprecated and no longer applied.
- Schema checks, SQLite rowid metadata, composite key handling, bounded append probes, per-batch accounting and package boundaries are substantial improvements. None of those positive changes cancels out silent JSON corruption.
- Recommendation for this bounded core review: candidate is the stronger development base, but do not merge it unconditionally until the confirmed data correctness/compatibility findings are resolved and targeted regressions pass.

## Limits

This was a bounded review of a very large main-to-candidate delta (83 src/manifest files; about 11.8k added lines). It does not certify all generators, plugins, PostgreSQL behavior, or performance. No new PostgreSQL/Docker test or full benchmark was run. Existing green CI/Sonar/mutation evidence is useful but did not cover these round trips; unique_adjuster mutation success does not validate the adapter JSON binding or the self-FK postpass. The requested long-term memory index did not exist; repository instructions were read.
