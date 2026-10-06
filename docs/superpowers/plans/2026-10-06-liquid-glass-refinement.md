# Liquid Glass refinement implementation plan

> For agentic workers: use subagent-driven-development with disjoint file ownership; review specification compliance and code quality before integration. User authorization permits autonomous implementation and routine design choices.

**Goal:** Deliver a verified refinement of the latest sqlseed workbench with stable data surfaces, coherent glass operations, reachable mobile editing and understandable confirmation feedback.

**Architecture:** Preserve the native ES modules and single model/session. Workbench presentation owns disclosures and confirmation status; shared CSS owns materials and target sizes; tab-motion owns only disposable decoration.

**Tech Stack:** FastAPI static assets, native JavaScript/CSS, Node built-in tests, pytest and real browser checks.

## 1. Baseline and evidence

- [x] Fetch origin and compare GitHub main, local HEAD, open PRs and main CI.
- [x] Reuse isolated `cf6a/sqlseed`; rename branch to `codex/liquid-glass-ui`. Preserve untracked historical reports.
- [x] Freeze main with git archive and start separate baseline/candidate ASGI previews, independent synthetic data and no inherited model credentials.
- [x] Run `node --test plugins/sqlseed-web/tests/test_*.cjs`: 1022 passed before changes.
- [x] Capture baseline scenes and timing evidence from the frozen main before comparing candidate results.

## 2. Workbench presentation

Files: `plugins/sqlseed-web/src/sqlseed_web/static/js/pages/workbench.js`, `workbench.css`, `js/i18n/messages/workbench.json`, associated workbench regression files.

- [x] Add failing behavioral checks for opening collapsed directory before generation/error focus; viewing a table must not change generation selection.
- [x] Implement narrow directory disclosure with current table and generation selection summary, preserving actual table controls and model view state.
- [x] Keep current guide action visible in a compact presentation, with details and steps available. Preserve stored expansion preference.
- [x] Expand independent checkbox touch labels and narrow count stepper targets without changing stepCount validation.
- [x] Add failing confirmation tests for checking, failure and blocked summary, detail navigation, and unchanged run authorization.
- [x] Implement footer status from structured execution state. Attach `aria-describedby`, keep details in the body and focus only on explicit navigation.
- [x] Run relevant execution, recovery, guidance, page, usability and bilingual tests, then inspect real narrow layouts.

## 3. Shared tab feedback

Files: `static/js/tab-motion.js`, `tests/test_tab_motion.cjs` (new).

- [x] Reproduce reduced-motion change before RAF, during horizontal animation and during vertical animation; test repeated selection, removal and independent groups.
- [x] Track pending frames and decoration handles; cancel on preference change, new selection and removal. Never animate label opacity.
- [x] Verify synchronous semantics and focus remain owned by the caller. Run new tests and existing segment/navigation tests.

## 4. Shared materials and navigation

Files: `static/style.css`, `navigation.css`, `motion.css` if required, `design-system.html`, `js/design-system.js` if required, existing component-standard docs.

- [x] Define data/control/overlay material roles in existing light/dark tokens. Map reading areas and nested confirmation facts to stable surfaces; reduce unnecessary broad blur.
- [x] Refine edge/shadow/focus hierarchy using shared variables. Keep brand/font assets unchanged and maintain fallback modes.
- [x] Make navigation and frequent controls reachable on narrow/coarse input; verify English labels, five viewport widths, no horizontal document overflow and sampled focus visibility.
- [x] Verify real browser 200% at native zoom=2 / scale=1, 319×332 CSS px. Check workbench/configurations/settings, confirmation/YAML/rule focus and scrolling; repair the run-table name compression and verify local table scrolling, keyboard access and current-data return at the same native zoom.
- [x] Update component reference and inspect the real rendered result, not just selectors.

## 5. Validation, review and delivery

- [x] Full Node suite; Web pytest within the offline repository run; required lint/format/type/import/doc/architecture and mutation checks. Record 29 platform/optional skips and 82 external-service deselections. Python result is 4400 deduplicated passes after the 51-test docs recheck, not a second full run.
- [x] After the final long-field CSS repair, re-run full Web Node: 1057/1057 on both October 6 and October 7; source/HTTP verification also passes.
- [x] Real browser samples: theme/language persistence and synchronization; five widths; keyboard/Escape/focus; reduced motion/transparency. No-filter evidence force-activates existing CSS declarations in a supporting engine; it is labeled as synthetic.
- [x] Close actual 200% browser acceptance after the minimal runs.css repair. The 30-step record ends with native zoom=2 / scale=1; children stays readable, the 560px table scrolls inside a 235px container, Tab/Enter opens read-only current data and Escape returns to the original button without document overflow.
- [x] Close the interrupted no-refresh result observation with a new explicit append on October 7: no manual refresh/reselection/navigation; initial and final AX show success, 7 inserted rows, parents 3 / children 4. Read-only SQLite now has 9 / 12 valid rows. The earlier fourth-run intermediate capture remains historical, not proof of all intermediate states.
- [x] Open the current-data UI before that append: children 8 rows, amount 7 / doubled 14, sorted by id, pagination disabled for the only page; no multipage claim.
- [x] Real disposable SQLite workflow: connect, edit invalid/cancel/apply, preview with unchanged row counts, save/reopen, explicit append and clear, inspect actual rows/FKs and run results.
- [x] Exercise configurations/filter/bulk operations, graph/view-selection independence, AI unavailable and labeled candidate review fixture, plugin status and existing protected-operation tests.
- [x] Capture before/after screenshots and comparable load/scroll/interaction metrics. Fix regressions without weakening assertions.
- [x] Independent specification and quality review, then verify fixes. October 7 final diff review found no P0/P1/P2 issues; 115 targeted tests passed. Earlier review fixes retained compact stage navigation and wide/coarse touch targets.
- [x] Commit only task source/docs/tests, push branch, create and attach [Draft PR #35](https://github.com/sunbos/sqlseed/pull/35). Implementation commit: `87c2a046b0a2c5493c98b6e5c950761df7fcdfb8`. No merge or release.
- [x] Inspect PR head `3e347cf7`: CI run 37544159614, doc-sync, Sonar, CodeFlow and codecov passed; the main-only docs job skipped, while lint built maintained docs. Any later run-table fix must have its own applicable checks and candidate-head CI.
- [x] Verify the run-table CSS follow-up with the same native-zoom browser flow and `node --test plugins/sqlseed-web/tests/test_runs.cjs`: 33/33 pass, no failures/skips. The earlier full 1064 result is not claimed as a new full run.
- [ ] Verify final candidate-head CI, then deliver the candidate URL, functional checklist, evidence index, validation results and explicit boundaries. Audit every goal requirement before marking complete.

## Evidence status — 2026-10-07

The [implementation report](../../ui-review/2026-10-06/liquid-glass-implementation.md) and its portable JSON summarize the evidence and preserve the remaining checks. Baseline/candidate services were safely restarted and reverified; do not reuse the previous process IDs as current provenance. No-refresh success and the current-data UI were rechecked after browser recovery. Native 200% browser acceptance is complete in the 30-step `native-200-acceptance-20261007.json`, including the minimal run-table readability repair and actual scroll/keyboard/data-view recheck. Earlier zoom=1 probes remain historical. The `3e347cf7` checks are green; the CSS follow-up now has 33/33 targeted checks, and the final delivery commit still requires its own CI. Untested live LLM, local browser PostgreSQL, real mobile/GPU, other browsers and XR remain disclosed boundaries, not expanded implementation scope.
