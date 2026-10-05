# macOS adaptation implementation plan

**Goal:** Make the latest five-package sqlseed checkout usable and maintainable on macOS Intel and Apple Silicon, including runtime behavior, installation, tests, CI and bilingual documentation, while preserving Windows/Linux support.

**Architecture:** Keep Core offline and preserve the five package boundaries. Repair demonstrated platform assumptions at their owning layer; retain real SQLite/PostgreSQL and installed-entrypoint acceptance. Do not change database contents or the user's existing checkout/environment.

**Tech stack:** Python 3.10+, SQLAlchemy, FastAPI, pytest, Node's test runner, hatchling, GitHub Actions, MkDocs.

## Baseline and evidence

- Baseline commit: `2c14563364f2e3a34038e14a0d2b37cabd0a2705`.
- Working branch: `codex/macos-adaptation`; original Desktop checkout remains unchanged.
- Local host: macOS 26.6.2, Intel x86_64; separate Python virtual environment.
- Reproduced: hash-locked binary-only CI dependency installation cannot install `cryptography==50.0.1` on Intel macOS. Preserve the current version and source hashes; limit any new source-build exception to this package on this architecture.
- Audit: macOS GPU discovery assumes Apple vendor; quickstart assumes an existing virtualenv belongs to the current OS and installs local packages separately.

## Work and acceptance checklist

- [x] Audit Core, CLI, AI, MCP, Web, scripts, tests, dependencies and maintained documentation for platform assumptions.
- [x] Reproduce and repair AI hardware detection with Intel/AMD/Apple data; document unified-memory estimates without promising model/backend compatibility.
- [x] Reproduce and repair any SQLite identity/locking and process-lifecycle differences using actual macOS filesystem and subprocess behavior.
- [x] Repair quickstart virtualenv validation, local five-package installation and commands; include docs dependencies in developer setup.
- [x] Provide a repeatable Intel dependency installation path without dependency downgrades or unrestricted source builds; cover Intel and Apple Silicon in CI.
- [x] Add paired macOS user/developer documentation and link it from maintained entry points; document Python, venv migration, native architecture, CLI/MCP paths and PostgreSQL setup.
- [x] Run full pytest with resource warnings as errors; distinguish real-service skips from executed tests.
- [x] Run real PostgreSQL integration using an isolated local service if available, and verify installed Core/CLI/MCP/Web entrypoints and SQLite writes from built distributions.
- [x] Run Node frontend/Pages regressions, ruff, format, mypy, import-linter, architecture/doc-sync checks, strict bilingual docs build and mutation gate.
- [x] Review final diff independently; record exact results and remaining external validation limitations before claiming completion.

Local acceptance, independent review and remote Intel/Apple Silicon/Windows/Linux CI are complete for implementation commit `71816f9`; see [the acceptance record](../../code-review/2026-10-05-macos-adaptation.md).

## Verification commands

Commands run from this worktree with its `.venv/bin` on PATH:

```sh
python -m pip check
ruff check src/ tests/ plugins/ scripts/quickstart.py
ruff format --check src/ tests/ plugins/ scripts/quickstart.py
mypy src/sqlseed/ plugins/
lint-imports
pytest -q --tb=short -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning
node --test plugins/sqlseed-web/tests/test_*.cjs tests/test_deploy_pages.cjs
python scripts/sync_docs.py --check
make docs-build
make mutmut
```

Source-only changes are tested first with a failing reproducer, then with focused tests and the full suite. Package acceptance builds sdist and wheel for all five packages and installs into clean temporary environments. No production database or user's AI credentials are used.
