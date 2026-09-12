# Quality Check Remediation Implementation Plan

> **For agentic workers:** Use subagent-driven-development to execute the independent package tasks, with integration review before each shared commit.

**Goal:** Restore all checks on PR #10, eliminate all valid Sonar findings, retain CodeFlow's zero findings, and document individually verified false positives without source suppression comments.

**Architecture:** Preserve the five-package boundary, offline streaming Core, seeded generation, database semantics, and existing Web lifecycle/security guarantees. Remediate by package ownership and coherent rule groups; configuration must reflect the real source/test scope.

**Tech Stack:** Python 3.10–3.13, pytest, Ruff, mypy, import-linter, Node tests, ESLint, Pylint, jscpd, GitHub Actions, SonarCloud, Codecov.

## Baseline and ownership

- Baseline commit: `49caea3ee2785db51c1b2d2c8940ee4f0a19cd2a`.
- Windows: one failure at the zero-time-budget boundary.
- Python 3.12: tests passed; Codecov returned `Repository not found` during upload.
- Sonar PR #10: 762 unresolved findings, comprising 12 vulnerabilities, 8 bugs, and 742 code smells. These classifications require source verification.
- CodeFlow: all three analyzers completed with zero errors and warnings.
- AI worker: `plugins/sqlseed-ai/` (102 findings).
- Web worker: `plugins/sqlseed-web/` (505 findings).
- Core worker: `src/sqlseed/` and root `tests/` (123 findings).
- Coordinator: CI/external integrations, CLI, scripts, examples, evidence (32 findings).

Preserve the pre-existing changes to `.sonarcloud.properties`, `docs/candidate-validation.md`, and the pre-existing untracked documentation/prototypes. Use the isolated `/tmp/sqlseed-codeflow-venv` environment; preserve the user's project environment and service on port 8630.

## 1. Deadline boundary

- [x] Reproduce `budget=0, elapsed=0` and `budget=5, elapsed=5` using a fixed monotonic clock; retain `budget=5, elapsed=4` as a nonexpired control.
- [x] Change the deadline check in `plugins/sqlseed-ai/src/sqlseed_ai/healer/orchestrator.py` from `>` to `>=`.
- [x] Run `pytest plugins/sqlseed-ai/tests/test_runtime.py plugins/sqlseed-ai/tests/healer/` and check Ruff, format, mypy, and Pylint on the changed files.
- [x] Review and commit only the two deadline files, push the candidate branch, and inspect the exact new Windows check. Commit `01b1584152aa1fc9f1135ea6add6fb1ab8c303be`; Windows job `103605398190` passed.

## 2. External integrations and effective scope

- [ ] Verify Codecov repository registration, account/repository authorization, and upload identity using the existing failed job. Preserve `fail_ci_if_error: true`.
- [ ] Confirm an authenticated browser/API session before account mutations; do not request secrets in chat.
- [ ] Verify the effective Sonar source/test classification and Python versions. Automatic analysis reads `.sonarcloud.properties` from the default branch; the file is absent on `main` at the baseline.
- [ ] Apply the narrow integration/configuration repair supported by those observations and verify it through a new scan/upload.

## 3. Findings by owned package

- [ ] Reconcile every baseline issue key with current source before editing.
- [ ] Fix valid security/reliability findings first; preserve callback veto, seeded randomness, exact sentinels, and local-only authority parsing.
- [ ] Refactor cognitive complexity by cohesive responsibilities with explicit inputs/results; preserve public signatures and failure cleanup.
- [ ] Improve repeated constants, assertions, exception tests, response documentation, JavaScript expressions, and CSS where the rule is applicable.
- [ ] For a confirmed false positive that cannot be removed by a useful behavior-preserving change, record the issue key, concrete source evidence, and applicable regression before using Sonar's false-positive status.
- [ ] Keep per-package issue disposition files for integration. Reconcile new findings after each remote scan, rather than assuming changed line numbers prove resolution.

## 4. Integration and completion evidence

- [ ] Review each batch for requirements and correctness, then run the relevant actual behavior tests.
- [ ] Run full Ruff/format/mypy/import contracts, pytest, Web Node tests, architecture/doc-sync checks, package smoke validation, and the repository mutation gate; resolve applicable failures rather than weakening gates.
- [ ] Run the CodeFlow analyzer versions/configuration against the integrated source before pushing the complete remediation batch.
- [ ] Inspect the exact pushed commit's GitHub checks, Codecov upload, CodeFlow report, and Sonar Quality Gate/findings.
- [ ] Complete only when all valid findings are resolved, all required checks pass, and every remaining confirmed false positive has individual evidence and an appropriate remote disposition.
