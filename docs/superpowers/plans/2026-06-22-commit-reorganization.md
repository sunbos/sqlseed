# Commit Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize 7 mixed commits (1dd2c29..640950e) into 17 fine-grained functional commits on `feat/multi-db-support` branch.

**Architecture:** Backup branch + `git reset --mixed 1dd2c29` + sequential `git add` + `git commit` per functional module. No code changes — only commit history rewrite.

**Tech Stack:** Git, PowerShell

**Spec:** `docs/superpowers/specs/2026-06-22-commit-reorganization-design.md`

---

## File Structure

All files already exist in the working tree after reset. No new files created (except the design doc already written). Each task stages specific files and commits them.

### Cross-commit Modified Files

These files were modified in multiple original commits and must be assigned to exactly one new commit:

| File | Assigned to | Reason |
|------|-------------|--------|
| `AGENTS.md` | Task 10 | Merges `13adf6b` + `1fe741f` changes |
| `CLAUDE.md` | Task 10 | Merges `13adf6b` + `1fe741f` changes |
| `pyproject.toml` | Task 13 | Merges `13adf6b` + `ac4147c` changes |

---

## Task 0: Safety Preparation

**Files:** None (git operations only)

- [ ] **Step 1: Verify current branch is feat/multi-db-support**

Run: `git branch --show-current`
Expected: `feat/multi-db-support`

- [ ] **Step 2: Verify HEAD is at 640950e**

Run: `git rev-parse --short HEAD`
Expected: `640950e`

- [ ] **Step 3: Create backup branch**

Run: `git branch feat/multi-db-support-backup`
Expected: No output (success)

- [ ] **Step 4: Verify backup branch points to same commit**

Run: `git rev-parse --short feat/multi-db-support-backup`
Expected: `640950e`

- [ ] **Step 5: Verify working tree is clean**

Run: `git status --short`
Expected: Empty output (clean working tree, except for the new design doc)

- [ ] **Step 6: Reset to 1dd2c29 (keep working tree changes)**

Run: `git reset --mixed 1dd2c29`
Expected: List of files reset

- [ ] **Step 7: Verify all changes are in working tree**

Run: `git status --short`
Expected: All 103+ files shown as modified (M) or untracked (??)

- [ ] **Step 8: Verify content matches backup**

Run: `git diff feat/multi-db-support-backup`
Expected: Empty output (content identical)

---

## Task 1: Commit plugins/sqlseed-ai/ source code

**Files:**
- `plugins/sqlseed-ai/src/sqlseed_ai/AGENTS.md`
- `plugins/sqlseed-ai/src/sqlseed_ai/__init__.py`
- `plugins/sqlseed-ai/src/sqlseed_ai/_client.py`
- `plugins/sqlseed-ai/src/sqlseed_ai/_json_utils.py`
- `plugins/sqlseed-ai/src/sqlseed_ai/_model_selector.py`
- `plugins/sqlseed-ai/src/sqlseed_ai/_prompts.py`
- `plugins/sqlseed-ai/src/sqlseed_ai/_tools.py`
- `plugins/sqlseed-ai/src/sqlseed_ai/analyzer.py`
- `plugins/sqlseed-ai/src/sqlseed_ai/config.py`
- `plugins/sqlseed-ai/src/sqlseed_ai/errors.py`
- `plugins/sqlseed-ai/src/sqlseed_ai/examples.py`
- `plugins/sqlseed-ai/src/sqlseed_ai/refiner.py`

- [ ] **Step 1: Stage files**

Run: `git add plugins/sqlseed-ai/src/sqlseed_ai/`
Expected: No output (success)

- [ ] **Step 2: Verify staged files**

Run: `git diff --cached --name-only`
Expected: 12 files under `plugins/sqlseed-ai/src/sqlseed_ai/`

- [ ] **Step 3: Commit**

Run: `git commit -m "refactor: optimize plugins/sqlseed-ai/ source code" -m "Split analyzer.py (842 lines) into analyzer.py (580) + _prompts.py (120) + _tools.py (80). Add 3-tier prompt system (full/compact/ultra-compact) for context overflow handling. Make resolve_model/resolve_base_url pure functions (no self mutation). Improve type safety: Any -> OpenAI/DataOrchestrator/httpx.Timeout. Add English docstrings to all source files."`
Expected: `12 files changed`

- [ ] **Step 4: Verify commit**

Run: `git log --oneline -1`
Expected: Commit with message `refactor: optimize plugins/sqlseed-ai/ source code`

---

## Task 2: Commit plugins/sqlseed-ai/ documentation

**Files:**
- `plugins/sqlseed-ai/AGENTS.md`
- `plugins/sqlseed-ai/README.md`
- `plugins/sqlseed-ai/README.zh-CN.md`

- [ ] **Step 1: Stage files**

Run: `git add plugins/sqlseed-ai/AGENTS.md plugins/sqlseed-ai/README.md plugins/sqlseed-ai/README.zh-CN.md`
Expected: No output (success)

- [ ] **Step 2: Verify staged files**

Run: `git diff --cached --name-only`
Expected: 3 files

- [ ] **Step 3: Commit**

Run: `git commit -m "docs: update plugins/sqlseed-ai/ documentation" -m "Update AGENTS.md/README.md/README.zh-CN.md with _prompts.py/_tools.py references. Fix API key fallback chain, timeout default, hook table, and function name (generate_column_config -> analyze_schema)."`
Expected: `3 files changed`

- [ ] **Step 4: Verify commit**

Run: `git log --oneline -1`
Expected: Commit with message `docs: update plugins/sqlseed-ai/ documentation`

---

## Task 3: Commit plugins/mcp-server-sqlseed/ source code

**Files:**
- `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/AGENTS.md`
- `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/__init__.py`
- `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/__main__.py`
- `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/config.py`
- `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/server.py`

- [ ] **Step 1: Stage files**

Run: `git add plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/`
Expected: No output (success)

- [ ] **Step 2: Verify staged files**

Run: `git diff --cached --name-only`
Expected: 5 files under `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/`

- [ ] **Step 3: Commit**

Run: `git commit -m "refactor: optimize plugins/mcp-server-sqlseed/ source code" -m "Fix byte/character check bug in yaml_config size validation. Fix hardcoded provider from mimesis to faker (required dependency). Rename _validate_db_path to _validate_db_target (handles both path and URL). Add Pydantic field_validator for port (1-65535) and host (non-empty). Convert all Chinese docstrings/comments to English."`
Expected: `5 files changed`

- [ ] **Step 4: Verify commit**

Run: `git log --oneline -1`
Expected: Commit with message `refactor: optimize plugins/mcp-server-sqlseed/ source code`

---

## Task 4: Commit plugins/mcp-server-sqlseed/ documentation and config

**Files:**
- `plugins/mcp-server-sqlseed/AGENTS.md`
- `plugins/mcp-server-sqlseed/README.md`
- `plugins/mcp-server-sqlseed/README.zh-CN.md`
- `plugins/mcp-server-sqlseed/pyproject.toml`

- [ ] **Step 1: Stage files**

Run: `git add plugins/mcp-server-sqlseed/AGENTS.md plugins/mcp-server-sqlseed/README.md plugins/mcp-server-sqlseed/README.zh-CN.md plugins/mcp-server-sqlseed/pyproject.toml`
Expected: No output (success)

- [ ] **Step 2: Verify staged files**

Run: `git diff --cached --name-only`
Expected: 4 files

- [ ] **Step 3: Commit**

Run: `git commit -m "docs: update plugins/mcp-server-sqlseed/ documentation and config" -m "Add date headers, convert Chinese to English, complete README tools table from 3 to 6 tools, add Gemma 4 integration chapter. Add ruff/mypy/pytest configuration to pyproject.toml."`
Expected: `4 files changed`

- [ ] **Step 4: Verify commit**

Run: `git log --oneline -1`
Expected: Commit with message `docs: update plugins/mcp-server-sqlseed/ documentation and config`

---

## Task 5: Commit plugins/mcp-server-sqlseed/ test suite

**Files:**
- `plugins/mcp-server-sqlseed/tests/__init__.py`
- `plugins/mcp-server-sqlseed/tests/conftest.py`
- `plugins/mcp-server-sqlseed/tests/test_server.py`
- `plugins/mcp-server-sqlseed/tests/test_validate_db_path.py`

- [ ] **Step 1: Stage files**

Run: `git add plugins/mcp-server-sqlseed/tests/`
Expected: No output (success)

- [ ] **Step 2: Verify staged files**

Run: `git diff --cached --name-only`
Expected: 4 files under `plugins/mcp-server-sqlseed/tests/`

- [ ] **Step 3: Commit**

Run: `git commit -m "test: add plugins/mcp-server-sqlseed/ test suite" -m "Add 4 test files: __init__.py, conftest.py, test_server.py (213 lines), test_validate_db_path.py (57 lines). Covers server functionality and db path validation."`
Expected: `4 files changed`

- [ ] **Step 4: Verify commit**

Run: `git log --oneline -1`
Expected: Commit with message `test: add plugins/mcp-server-sqlseed/ test suite`

---

## Task 6: Commit sqlseed-ai plugin test suite

**Files:**
- `tests/test_ai_analyzer_streaming.py`
- `tests/test_ai_client.py`
- `tests/test_ai_config.py`
- `tests/test_ai_errors.py`
- `tests/test_ai_json_utils.py`
- `tests/test_ai_model_selector.py`
- `tests/test_ai_plugin_init.py`
- `tests/test_ai_prompts_tools.py`

- [ ] **Step 1: Stage files**

Run: `git add tests/test_ai_analyzer_streaming.py tests/test_ai_client.py tests/test_ai_config.py tests/test_ai_errors.py tests/test_ai_json_utils.py tests/test_ai_model_selector.py tests/test_ai_plugin_init.py tests/test_ai_prompts_tools.py`
Expected: No output (success)

- [ ] **Step 2: Verify staged files**

Run: `git diff --cached --name-only`
Expected: 8 files starting with `tests/test_ai_`

- [ ] **Step 3: Commit**

Run: `git commit -m "test: add sqlseed-ai plugin test suite" -m "Add 8 new test files (105 tests total) covering P0+P1+P2 gaps: analyzer streaming, client, config, errors, json_utils, model_selector, plugin init, prompts/tools."`
Expected: `8 files changed`

- [ ] **Step 4: Verify commit**

Run: `git log --oneline -1`
Expected: Commit with message `test: add sqlseed-ai plugin test suite`

---

## Task 7: Commit tests/ language unification and type annotations

**Files:**
- `tests/conftest.py`
- `tests/integration/test_pg_integration.py`
- `tests/integration/test_url_e2e.py`
- `tests/test_ai_plugin.py`
- `tests/test_cli.py`
- `tests/test_config/test_loader.py`
- `tests/test_config/test_models.py`
- `tests/test_database/test_adapter_contract.py`
- `tests/test_database/test_dialect.py`
- `tests/test_database/test_optimizer.py`
- `tests/test_database/test_sqlalchemy_adapter_boundary.py`
- `tests/test_orchestrator.py`
- `tests/test_orchestrator_adapter.py`

- [ ] **Step 1: Stage files**

Run: `git add tests/conftest.py tests/integration/ tests/test_ai_plugin.py tests/test_cli.py tests/test_config/test_loader.py tests/test_config/test_models.py tests/test_database/test_adapter_contract.py tests/test_database/test_dialect.py tests/test_database/test_optimizer.py tests/test_database/test_sqlalchemy_adapter_boundary.py tests/test_orchestrator.py tests/test_orchestrator_adapter.py`
Expected: No output (success)

- [ ] **Step 2: Verify staged files**

Run: `git diff --cached --name-only`
Expected: 13 files under `tests/`

- [ ] **Step 3: Commit**

Run: `git commit -m "test: unify tests/ language to English and improve type annotations" -m "Convert all Chinese docstrings and comments to English across 13 test files to comply with PEP 8/257. Type annotation improvements: tmp_path: Any -> tmp_path: Path (with TYPE_CHECKING import), monkeypatch: Any -> pytest.MonkeyPatch. Add module-level docstrings to all test files."`
Expected: `13 files changed`

- [ ] **Step 4: Verify commit**

Run: `git log --oneline -1`
Expected: Commit with message `test: unify tests/ language to English and improve type annotations`

---

## Task 8: Commit sql_safe and schema_helpers unit tests

**Files:**
- `tests/test_database/test_sql_safe.py`
- `tests/test_utils/test_schema_helpers.py`

- [ ] **Step 1: Stage files**

Run: `git add tests/test_database/test_sql_safe.py tests/test_utils/test_schema_helpers.py`
Expected: No output (success)

- [ ] **Step 2: Verify staged files**

Run: `git diff --cached --name-only`
Expected: 2 files

- [ ] **Step 3: Commit**

Run: `git commit -m "test: add sql_safe and schema_helpers unit tests" -m "Add test_sql_safe.py (7 lines modified) and test_schema_helpers.py (171 lines new). Both already in English, pass quality checks."`
Expected: `2 files changed`

- [ ] **Step 4: Verify commit**

Run: `git log --oneline -1`
Expected: Commit with message `test: add sql_safe and schema_helpers unit tests`

---

## Task 9: Commit optimization design specifications

**Files:**
- `docs/superpowers/specs/2026-06-20-project-consolidation-design.md`
- `docs/superpowers/specs/2026-06-21-cli-optimization-design.md`
- `docs/superpowers/specs/2026-06-21-config-optimization-design.md`
- `docs/superpowers/specs/2026-06-21-core-optimization-design.md`
- `docs/superpowers/specs/2026-06-21-database-optimization-design.md`
- `docs/superpowers/specs/2026-06-21-generators-optimization-design.md`
- `docs/superpowers/specs/2026-06-21-language-unification-design.md`
- `docs/superpowers/specs/2026-06-21-plugins-optimization-design.md`
- `docs/superpowers/specs/2026-06-21-root-and-holistic-review-design.md`
- `docs/superpowers/specs/2026-06-21-sqlseed-ai-optimization-design.md`
- `docs/superpowers/specs/2026-06-21-utils-optimization-design.md`
- `docs/superpowers/specs/2026-06-21-mcp-server-optimization-design.md`
- `docs/superpowers/specs/2026-06-21-sqlseed-ai-tests-docs-design.md`
- `docs/superpowers/specs/2026-06-22-project-wide-optimization-design.md`
- `docs/superpowers/specs/2026-06-22-commit-reorganization-design.md`

- [ ] **Step 1: Stage files**

Run: `git add docs/superpowers/specs/`
Expected: No output (success)

- [ ] **Step 2: Verify staged files**

Run: `git diff --cached --name-only`
Expected: 15 files under `docs/superpowers/specs/`

- [ ] **Step 3: Commit**

Run: `git commit -m "docs: add optimization design specifications" -m "Add 15 design documents for optimization rounds: project-consolidation, cli, config, core, database, generators, language-unification, plugins, root-and-holistic-review, sqlseed-ai, utils, mcp-server, sqlseed-ai-tests-docs, project-wide-optimization, and commit-reorganization."`
Expected: `15 files changed`

- [ ] **Step 4: Verify commit**

Run: `git log --oneline -1`
Expected: Commit with message `docs: add optimization design specifications`

---

## Task 10: Commit brand positioning update

**Files:**
- `AGENTS.md`
- `CLAUDE.md`
- `GEMINI.md`
- `README.md`
- `README.zh-CN.md`
- `docs/index.md`

**Note:** `AGENTS.md` and `CLAUDE.md` merge changes from original commits `13adf6b` + `1fe741f`.

- [ ] **Step 1: Stage files**

Run: `git add AGENTS.md CLAUDE.md GEMINI.md README.md README.zh-CN.md docs/index.md`
Expected: No output (success)

- [ ] **Step 2: Verify staged files**

Run: `git diff --cached --name-only`
Expected: 6 files

- [ ] **Step 3: Commit**

Run: `git commit -m "docs: update brand positioning from SQLite-only to Multi-Database" -m "Update project description across root-level documentation files to reflect the multi-database architecture (SQLite, PostgreSQL, MySQL). AGENTS.md, CLAUDE.md, GEMINI.md: project overview now mentions PostgreSQL and MySQL support via SQLAlchemy. README.md, README.zh-CN.md: add PostgreSQL/MySQL installation instructions and connection examples. docs/index.md: add multi-database quick start examples. Also includes project knowledge base updates in AGENTS.md and CLAUDE.md."`
Expected: `6 files changed`

- [ ] **Step 4: Verify commit**

Run: `git log --oneline -1`
Expected: Commit with message `docs: update brand positioning from SQLite-only to Multi-Database`

---

## Task 11: Commit examples/ language unification

**Files:**
- `examples/quick_demo.py`
- `examples/build_demo_db.py`
- `examples/notebooks/01-quickstart.ipynb`
- `examples/notebooks/02-column-mapping.ipynb`
- `examples/notebooks/03-generators.ipynb`
- `examples/notebooks/04-database-advanced.ipynb`
- `examples/notebooks/05-dag-and-constraints.ipynb`
- `examples/notebooks/06-config-deep-dive.ipynb`
- `examples/notebooks/07-ai-plugin.ipynb`
- `examples/notebooks/08-mcp-server.ipynb`
- `examples/notebooks/09-plugin-hooks.ipynb`
- `examples/notebooks/10-cli-reference.ipynb`
- `examples/notebooks/11-utilities.ipynb`
- `examples/notebooks/12-testing-patterns.ipynb`

- [ ] **Step 1: Stage files**

Run: `git add examples/quick_demo.py examples/build_demo_db.py examples/notebooks/`
Expected: No output (success)

- [ ] **Step 2: Verify staged files**

Run: `git diff --cached --name-only`
Expected: 14 files under `examples/`

- [ ] **Step 3: Commit**

Run: `git commit -m "docs: unify examples/ language to English" -m "Translate all Chinese content to English across 14 example files: quick_demo.py, build_demo_db.py (docstrings, comments, console output), and 12 notebooks (markdown cells, code comments, output). Complies with PEP 8/257 and project language unification standards."`
Expected: `14 files changed`

- [ ] **Step 4: Verify commit**

Run: `git log --oneline -1`
Expected: Commit with message `docs: unify examples/ language to English`

---

## Task 12: Commit docs/specs/ and docs/superpowers/plans/ language unification

**Files:**
- `docs/specs/2026-06-19-multi-db-support-design.md`
- `docs/specs/2026-06-20-multi-db-test-completion-design.md`
- `docs/specs/2026-06-20-project-consolidation-design.md`
- `docs/superpowers/plans/2026-06-20-cp1-p0-core-features.md`
- `docs/superpowers/plans/2026-06-20-cp2-p1-boundary-contract.md`
- `docs/superpowers/plans/2026-06-20-cp3-p2-integration-e2e.md`

- [ ] **Step 1: Stage files**

Run: `git add docs/specs/ docs/superpowers/plans/`
Expected: No output (success)

- [ ] **Step 2: Verify staged files**

Run: `git diff --cached --name-only`
Expected: 6 files (3 in `docs/specs/`, 3 in `docs/superpowers/plans/`)

- [ ] **Step 3: Commit**

Run: `git commit -m "docs: unify docs/specs/ and docs/superpowers/plans/ language to English" -m "Translate all Chinese content to English across 6 historical design documents and implementation plans. No code logic changes — text content only."`
Expected: `6 files changed`

- [ ] **Step 4: Verify commit**

Run: `git log --oneline -1`
Expected: Commit with message `docs: unify docs/specs/ and docs/superpowers/plans/ language to English`

---

## Task 13: Commit CI and dev tooling configuration

**Files:**
- `.github/workflows/ci.yml`
- `.pre-commit-config.yaml`
- `pyproject.toml`
- `mkdocs.yml`

**Note:** `pyproject.toml` merges changes from original commits `13adf6b` + `ac4147c`.

- [ ] **Step 1: Stage files**

Run: `git add .github/workflows/ci.yml .pre-commit-config.yaml pyproject.toml mkdocs.yml`
Expected: No output (success)

- [ ] **Step 2: Verify staged files**

Run: `git diff --cached --name-only`
Expected: 4 files

- [ ] **Step 3: Commit**

Run: `git commit -m "ci: add PostgreSQL integration tests and expand dev tooling" -m "Add integration job with PostgreSQL 16 container service to CI. Expand pre-commit hooks from 2 to 10 (ruff, mypy, trailing-whitespace, end-of-file-fixer, check-yaml/toml/merge-conflict/added-large-files). Exclude examples/notebooks from ruff linting (educational notebooks). Fix mkdocs.yml site_url to sunbos.github.io/sqlseed/ and expand nav with User Guide and API Reference."`
Expected: `4 files changed`

- [ ] **Step 4: Verify commit**

Run: `git log --oneline -1`
Expected: Commit with message `ci: add PostgreSQL integration tests and expand dev tooling`

---

## Task 14: Commit project configuration files

**Files:**
- `.editorconfig`
- `.env.example`
- `Makefile`

- [ ] **Step 1: Stage files**

Run: `git add .editorconfig .env.example Makefile`
Expected: No output (success)

- [ ] **Step 2: Verify staged files**

Run: `git diff --cached --name-only`
Expected: 3 files

- [ ] **Step 3: Commit**

Run: `git commit -m "chore: add project configuration files" -m "Add .editorconfig (cross-editor consistency: UTF-8, LF, 4-space Python, 2-space YAML). Add .env.example (all environment variables documented: SQLSEED_LOG_LEVEL, SQLSEED_CACHE_DIR, SQLSEED_AI_*, GOOGLE_API_KEY, OPENAI_API_KEY). Add Makefile (12 common dev targets: install, lint, format, type-check, test, docs, clean)."`
Expected: `3 files changed`

- [ ] **Step 4: Verify commit**

Run: `git log --oneline -1`
Expected: Commit with message `chore: add project configuration files`

---

## Task 15: Commit community files

**Files:**
- `CONTRIBUTING.md`
- `SECURITY.md`
- `CODE_OF_CONDUCT.md`

- [ ] **Step 1: Stage files**

Run: `git add CONTRIBUTING.md SECURITY.md CODE_OF_CONDUCT.md`
Expected: No output (success)

- [ ] **Step 2: Verify staged files**

Run: `git diff --cached --name-only`
Expected: 3 files

- [ ] **Step 3: Commit**

Run: `git commit -m "docs: add community files" -m "Add CONTRIBUTING.md (development setup, code standards, commit convention, PR process). Add SECURITY.md (supported versions, vulnerability reporting, response timeline). Add CODE_OF_CONDUCT.md (Contributor Covenant 2.1, bilingual)."`
Expected: `3 files changed`

- [ ] **Step 4: Verify commit**

Run: `git log --oneline -1`
Expected: Commit with message `docs: add community files`

---

## Task 16: Commit GitHub templates and CODEOWNERS

**Files:**
- `.github/CODEOWNERS`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/ISSUE_TEMPLATE/bug_report.md`
- `.github/ISSUE_TEMPLATE/feature_request.md`

- [ ] **Step 1: Stage files**

Run: `git add .github/CODEOWNERS .github/PULL_REQUEST_TEMPLATE.md .github/ISSUE_TEMPLATE/`
Expected: No output (success)

- [ ] **Step 2: Verify staged files**

Run: `git diff --cached --name-only`
Expected: 4 files under `.github/`

- [ ] **Step 3: Commit**

Run: `git commit -m "chore: add GitHub templates and CODEOWNERS" -m "Add .github/CODEOWNERS (default owner @sunbos + path-specific rules). Add .github/PULL_REQUEST_TEMPLATE.md (PR template with testing checklist). Add .github/ISSUE_TEMPLATE/bug_report.md and feature_request.md (issue templates with environment, config, error output sections)."`
Expected: `4 files changed`

- [ ] **Step 4: Verify commit**

Run: `git log --oneline -1`
Expected: Commit with message `chore: add GitHub templates and CODEOWNERS`

---

## Task 17: Commit API reference and user guide

**Files:**
- `docs/api.md`
- `docs/guide.md`

- [ ] **Step 1: Stage files**

Run: `git add docs/api.md docs/guide.md`
Expected: No output (success)

- [ ] **Step 2: Verify staged files**

Run: `git diff --cached --name-only`
Expected: 2 files

- [ ] **Step 3: Commit**

Run: `git commit -m "docs: add API reference and user guide" -m "Add docs/api.md (full Python API reference, 522 lines: Public API, Configuration Models, Result Types, DataOrchestrator, Database Adapter Protocol, Module Exports). Add docs/guide.md (user guide, 685 lines: Installation, Quick Start, Multi-Database Support, CLI Reference, YAML Configuration, AI Plugin, MCP Server, 9-Level Column Mapping, Plugin System, Troubleshooting)."`
Expected: `2 files changed`

- [ ] **Step 4: Verify commit**

Run: `git log --oneline -1`
Expected: Commit with message `docs: add API reference and user guide`

---

## Task 18: Final Verification

**Files:** None (verification only)

- [ ] **Step 1: Verify working tree is clean**

Run: `git status --short`
Expected: Empty output (all files committed)

- [ ] **Step 2: Verify commit count**

Run: `git rev-list 1dd2c29..HEAD --count`
Expected: `17`

- [ ] **Step 3: Verify content matches backup**

Run: `git diff feat/multi-db-support-backup HEAD`
Expected: Empty output (content identical)

- [ ] **Step 4: Verify commit log**

Run: `git log --oneline 1dd2c29..HEAD`
Expected: 17 commits in reverse chronological order

- [ ] **Step 5: Run ruff check**

Run: `ruff check .`
Expected: `All checks passed!`

- [ ] **Step 6: Run mypy**

Run: `mypy src plugins`
Expected: `Success: no issues found in 72 source files`

- [ ] **Step 7: Run pytest**

Run: `pytest --tb=short -q`
Expected: `964 passed, 2 skipped` (3 errors from Docker-unavailable PG tests are acceptable)

- [ ] **Step 8: Run mkdocs build**

Run: `mkdocs build --strict`
Expected: `Documentation built in X.XX seconds`

- [ ] **Step 9: Verify CLI**

Run: `sqlseed --help`
Expected: CLI help output

- [ ] **Step 10: Final summary**

Run: `git log --oneline 1dd2c29..HEAD && Write-Host "" && Write-Host "=== Verification complete ===" && Write-Host "Commits: $(git rev-list 1dd2c29..HEAD --count)" && Write-Host "Content diff: $(git diff feat/multi-db-support-backup HEAD --stat)"`
Expected: 17 commits listed, verification complete

---

## Rollback Procedure

If any task fails or verification shows issues:

- [ ] **Step 1: Reset to backup**

Run: `git reset --hard feat/multi-db-support-backup`
Expected: HEAD now at 640950e

- [ ] **Step 2: Verify restoration**

Run: `git log --oneline -7`
Expected: Original 7 commits restored

- [ ] **Step 3: Delete backup branch (only after successful verification)**

Run: `git branch -d feat/multi-db-support-backup`
Expected: `Deleted branch feat/multi-db-support-backup`
