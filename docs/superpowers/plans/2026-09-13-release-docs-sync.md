# Release and Documentation Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align README, published documentation and package metadata with the five-package implementation, then prepare a reviewable PyPI release and public-index verification procedure.

**Architecture:** Documentation follows current source contracts. Published PyPI 0.2.3 remains a separate version until a new release is authorized; no production API changes are needed for these corrections. Keep historical review/design documents in the repository and outside public site search.

**Tech Stack:** Markdown, MkDocs Material, hatchling/hatch-vcs, PyPI JSON, pip, pytest, existing installed-wheel smoke checks.

---

## Task 1: README examples and installation

**Files:** `README.md`, `README.zh-CN.md`.

- [x] State the version boundary between main's five-package implementation and published releases. Provide a working source installation that resolves local Core and plugins together. Show compatible PyPI version constraints and refer readers to tagged documentation for older installations.
- [x] Quote pip extras for zsh; identify which package provides each console command. Use absolute Pages/repository links that remain valid in PyPI descriptions and installed sdists.
- [x] Replace unsupported automatic age-range and ordinary same-name column association promises with accurate behavior and explicit configuration. Preserve the real `db.fill` alias and `seed` parameter.
- [x] Add `time` to the English generator reference, correct stale counts from the actual dispatch registry, include Web and current required dependencies, remove obsolete module paths, and align both languages.
- [x] Make AI examples select a backend explicitly and document the actual backend/protocol matrix. Update snapshot naming and all verified command/example mismatches found by the runtime audit.

## Task 2: Maintained docs and site scope

**Files:** `docs/index.md`, `docs/guide.md`, `docs/api.md`, `docs/architecture.md`, `docs/architecture.zh-CN.md`, `docs/gemma4-integration.md`, `docs/gemma4-integration.zh-CN.md`, `docs/migration.md`, `docs/migration.zh-CN.md`, `docs/web-workbench.md`, `docs/maintainable-release.md`, `docs/project-showcase.md`, `mkdocs.yml`.

- [x] Correct Core-versus-CLI installation, release availability, SQLite/PostgreSQL feature boundaries, and actual configuration/API signatures.
- [x] Match CLI options and all eight commands to `--help`; select Google explicitly in Google examples; separate the two offline MCP tools from the four AI MCP tools and their server commands.
- [x] Update architecture and metadata models from current manifests and dataclasses. Preserve automatic marker ownership by running `python scripts/sync_docs.py` rather than editing generated values.
- [x] Add `/candidate-validation.md` to `exclude_docs`; retain its source and the existing excluded audit/design directories. Verify its absence from the built search index.

## Task 3: PyPI content and distribution metadata

**Files:** five `pyproject.toml` files, four plugin `README.md` files, AI/MCP Chinese READMEs, and the five `LICENSE` files.

- [x] Align plugin descriptions, supported dependency series and entry points with their manifests without changing dependencies or version policy.
- [x] Set `Documentation` to existing Pages routes: Core `/`, CLI/MCP `/guide/`, AI `/gemma4-integration/`, Web `/web-workbench/` on `https://sunbos.github.io/sqlseed`.
- [x] Preserve the existing root license notice and append the complete official AGPLv3 text. Declare `license-files = ["LICENSE"]` and copy the combined file into plugin package roots; verify archive contents and hashes after building.
- [x] Keep a dated audit of the actual public versions: Core/AI/MCP 0.2.3; CLI/Web JSON endpoints currently return 404. Do not infer account ownership or Trusted Publisher configuration from public 404 responses.

## Task 4: Verification and release decision

**Artifacts:** `/tmp/sqlseed-release-docs-audit/` contains public-source snapshots, runtime probes, build logs and release preview artifacts. A maintained release procedure will document the exact public-index checks.

- [x] Baseline `pytest tests/test_doc_sync.py tests/test_architecture.py -q`: 32 passed. Baseline `scripts/sync_docs.py --check` and `mkdocs build --strict` pass.
- [x] Run changed documentation examples against temporary real SQLite databases and the actual five source packages; verify outcomes rather than only successful imports. Isolate model environment variables and make no real LLM request.
- [x] Run doc sync and architecture checks, strict MkDocs, source-to-reference coverage checks, and rendered-page/link/search-index checks. Obtain independent specification and quality review before integration.
- [x] Build five wheel/sdist pairs for a clearly labelled local 0.2.4 release preview without tagging or publishing; run `twine check --strict`, metadata/license/link inspection and fresh installed-wheel smoke checks.
- [x] Prepare release notes and an online verification procedure: fetch exact versions from official PyPI, verify wheel/sdist identities and versions, install into clean environments without editable imports, run `pip check`, console entry-point checks, and the existing real Core/Web smoke script. Include offline MCP invocation; explicitly distinguish this from real LLM validation.
- [ ] Present the exact release candidate and request final authorization before creating a public PyPI release. A GitHub merge, local wheel or TestPyPI installation is not evidence that production PyPI was updated.

## Verified local result (2026-09-13)

- All changes are documentation, package presentation/license inclusion, and release verification scripts. Runtime source, public APIs, dependency constraints and lock files are unchanged.
- Root and plugin README examples were exercised against disposable SQLite databases. Independent review found and fixed demo parent ordering, existing FK graph clearing, transform target columns and configuration completeness.
- Full source suite: 3646 passed, 65 skipped (unavailable PostgreSQL/LLM environments and optional integration conditions). Node: 669 passed. Ruff, format, mypy (166 source files), import boundaries and the 32 doc-sync/architecture checks passed.
- Strict MkDocs passed. All 1761 local links/anchors in 14 generated HTML files resolved; the search index excludes historical candidate/audit content. Generated HTML checks do not replace browser visual acceptance.
- Five local preview wheels and five sdists use the explicit temporary version override 0.2.4. Strict metadata checks, exact README contents, the preserved notice plus complete GNU license text, and hashes passed for all ten artifacts.
- Fresh full wheel (Python 3.13), minimal Core/Web wheel (Python 3.12) and full sdist (Python 3.12) environments passed installed-package checks. Core/Web each wrote 5 rows, the installed CLI wrote 7, the offline MCP server wrote 5, and the separate AI MCP server exposed 4 tools.
- Release script review fixed inherited pip configuration and direct CLI function invocation. Negative probes rejected external pip target/index settings, no-op console entry points, wrong versions/hashes/origins/artifact kinds and missing packages. Public 0.2.3 reports were used only to validate metadata logic; no public 0.2.4 acceptance was claimed.
- Preview artifacts, draft release notes and test evidence are in `/tmp/sqlseed-release-docs-audit/`. Actual PyPI upload, tag/release creation, publishing account configuration and post-upload acceptance remain a separate release decision.

- The README source-install command also passed an isolated resolver dry run with all five local packages. The unchanged default mutation target, tests and effective tool/dependency configuration were compared against the earlier 246/246-killed result.
