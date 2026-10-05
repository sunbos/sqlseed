# macOS adaptation acceptance record

Date: 2026-10-05. Baseline: `2c14563364f2e3a34038e14a0d2b37cabd0a2705`.

## Scope

The five-package checkout was audited for macOS installation, filesystem identity, hardware discovery, resource lifetime, process shutdown, tests, CI and documentation. Core remains offline; Windows/Linux behavior and optional plugin boundaries remain covered. The original Desktop checkout and its uncommitted files were preserved; work used a separate managed worktree.

Repairs cover native macOS GPU/vendor detection and conservative Apple unified-memory estimates; AI HTTP/client/stream cleanup; APFS SQLite identity across case and Unicode aliases without releasing database locks; quickstart virtualenv validation and local package resolution; native Intel/Apple Silicon CI; and paired macOS installation/development guides.

## Local evidence

Host: Intel x86_64 macOS 26.6.2, fresh Python 3.11.15 virtualenv, Node 24.21.0. All five local packages were installed together with the CI hash locks. PostgreSQL tests used isolated testcontainers on Docker Desktop.

| Check | Result |
| --- | --- |
| Full pytest, ResourceWarning and PytestUnraisableExceptionWarning treated as errors | 4459 passed, 33 skipped, 486.46 seconds |
| PostgreSQL integration | Real isolated PostgreSQL ran; 70 PostgreSQL-named cases passed in the full suite |
| Web and Pages Node regressions | 1069 passed, no skips or failures |
| pip check; ruff check and format; mypy; import-linter | Passed; mypy checked 175 source files |
| Architecture, package boundaries and doc-sync tests | Included in passing full suite |
| sync_docs --check and strict bilingual MkDocs build | Passed |
| make mutmut in an isolated copy | 246/246 killed; no survivors, timeouts or suspicious mutants |
| Five-package sdist-to-wheel builds and twine strict checks | Passed |
| Fresh wheel-only full installation | Core/Web/CLI/MCP performed actual SQLite writes; AI MCP discovery and bilingual assets passed |
| Fresh Core + Web installation without CLI/AI/MCP | Actual SQLite writes, optional-component state and bilingual assets passed |
| Installed sqlseed-web console | HTTP health and workbench served on 127.0.0.1:8630; SIGINT exited 0 and released the port |
| AI probe regression without MCP actually installed | 2 config tests passed; only MCP case skipped |
| Independent final-diff review | No unresolved P1/P2 findings |

The full-suite skips were 24 Win32-only cases, 6 unavailable LM Studio model cases, 2 filesystem cases requiring distinct case/normalization filenames, and 1 optional Pillow validation. Available local Ollama integration cases executed; this is not a claim that every AI model/backend was tested. The optional MCP import adjustment was separately verified after the full-suite run, both with and without MCP installed.

Intel dependency installation was tested with a fresh source build of the exact locked `cryptography==50.0.1`, hash-locked Python build tools, Rust 1.99.0, Clang and Homebrew OpenSSL 3. No runtime downgrade or general source-build allowance was introduced. Produced wheel SHA256: `ec463b9579fc819f917a00e3d20a702db7a1c933250e63f962839da815a8158d`.

Raw local evidence is retained at `/tmp/sqlseed-macos-{pytest-final,quality-final,node,mutation,packages-final,console,ai-without-mcp,crypto-build-final}.log`; these are task-local diagnostics, not product dependencies. Full pytest JUnit is `/tmp/sqlseed-macos-pytest-final.xml`.

## Cross-platform CI

Implementation commit `71816f92b8efa65723bebf7d1b5bfcddb726548f` passed [CI run 37332914031](https://github.com/sunbos/sqlseed/actions/runs/37332914031) and [doc-sync run 37332913266](https://github.com/sunbos/sqlseed/actions/runs/37332913266) on [draft PR #33](https://github.com/sunbos/sqlseed/pull/33). This follow-up changes only acceptance documentation.

| Remote environment | pytest | Node regressions |
| --- | --- | --- |
| macos-15 ARM64 / Python 3.12 | 4381 passed, 111 skipped | 1069 passed |
| macos-15 ARM64 / Python 3.13 | 4381 passed, 111 skipped | 1069 passed |
| macos-15-intel / Python 3.12 | 4381 passed, 111 skipped | 1069 passed |
| Windows / Python 3.12 | 4390 passed, 102 skipped | Not part of this job |
| Linux / Python 3.10, 3.12, 3.13 | Each 4437 passed, 55 skipped | Validated by lint job |
| Dedicated PostgreSQL 16 job | 59 passed | Not applicable |
| Property-test job | 3 passed | Not applicable |

All lint, package build/install and documentation jobs passed. The Intel runner built the locked cryptography release from source. The macOS skips comprise PostgreSQL without Docker (64), unavailable real LLM backends/models (18), Win32-only behavior (24), optional uv (2), Pillow (1), and distinct filesystem spelling cases (2). Windows/Linux likewise retain explicit external-service and platform skips; the dedicated PostgreSQL job and local service-backed run provide complementary coverage.

The latest pull-request checks are the source of current branch status. No release, deployment or merge was performed.


## Closure follow-up (2026-10-06)

The documentation-only head `eaf7d5e2f78299c4e5adab33cf8eed3b35030e00` also passed all GitHub Actions jobs, but its separate Codecov patch check reported 85% against an inherited 89.8% target. Eleven missing lines were Darwin-only SQLite identity code: macOS tests had executed successfully, while only Linux and Windows coverage was uploaded. One additional missing line handled malformed GPU names.

The follow-up collects coverage during native macOS tests and uploads the ARM64 and Intel Python 3.12 reports through the existing verified uploader. Codecov waits for all four platform reports; target inheritance, zero threshold, required report handling and upload failure gates remain unchanged. Hardware regression coverage now includes non-string names and preservation of other valid devices.

Branch protection still required the earlier macOS and Windows check names. Windows retains its protected name; a macOS compatibility gate retains the other name and requires the entire expanded matrix to succeed. Its actual script is tested against success, failure, cancellation and skip outcomes. Pages continues to depend on every CI job.

Three Sonar complexity findings prompted behavior-preserving extraction of GPU memory parsing and quickstart environment installation, plus an ExitStack for stream/client cleanup. Optional AI test imports now skip only when the top-level plugin is absent; missing internal modules or required SDKs still fail. Other CodeFlow style findings are addressed without weakening collection assertions or disabling rules.

The formal review also identified that quickstart's displayed Windows commands could split paths containing `&` in cmd.exe. Windows output now identifies PowerShell and uses literal arguments with the call operator; POSIX output remains unchanged. Regression tests execute the generated command through Windows PowerShell and, when installed, PowerShell 7, then compare the Python process's actual arguments, including shell metacharacters and smart quotation marks. The Windows compatibility job runs these native checks; the local macOS environment skips both cases because neither PowerShell executable is installed.

Local follow-up evidence includes 1290 passing AI/identity/architecture/documentation tests with 8 explicit external-service/filesystem skips, strict resource warnings, all 175 source files passing mypy, ruff/format, import boundaries, documentation sync and strict MkDocs build. The final targeted run separately covers the small style/import adjustments: 118 passed with 2 filesystem skips, 100% hardware line coverage and 95% SQLite identity line coverage; all previously missed Darwin lines were executed. Final platform, Codecov, Sonar and review outcomes are available in [PR #33 checks](https://github.com/sunbos/sqlseed/pull/33/checks), which remain authoritative for the latest commit.
