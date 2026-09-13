# Package and documentation validation

Environment: macOS 26.6.2 x86_64, CPython 3.12.13. Source checkout unchanged by this verification task.

- Five sdist -> wheel builds: passed. AI wheel contains the final Decimal literal precision fix.
- Twine strict: all ten distributions passed.
- Full install: five non-editable local wheels, pip check and source-external smoke passed.
- Minimal install: Core + Web only, all 23 applicable requirements-minimal hash-locked versions, pip check and source-external smoke passed.
- Full environment has all 139 applicable CI lock versions, no editable distributions.
- Both smokes generated five Core rows and five workbench rows, checked non-writing preview, assets, origin rejection, component availability, and worker cleanup.
- MkDocs --strict passed; site output: `/tmp/sqlseed-codeflow-packages-bp87t1jx/site`.
- User .venv still has neither sqlseed-ai nor mcp-server-sqlseed. Port 8630 was not operated.

## Platform prerequisite exception

cryptography 50.0.1 publishes macOS arm64 wheels but no x86_64 wheel. The unmodified only-binary CI dependency command failed. Allowing source builds without isolation also failed because maturin was absent. The same-version x86_64 wheel already built and used by the known-good dev environment was installed from uv's cache, with its SHA256 recorded. The original hash-locked CI requirements then installed successfully; no version pins or repository files changed.

## Evidence

`commands.jsonl` records argv, cwd, log path, exit status and elapsed time. `result.json` aggregates the final checks. `artifacts.json` contains all ten SHA256 digests. `all-wheel-source-payload-audit.json` confirms 206 packaged source/assets files match the checkout, including newly added helpers. `full-install-audit.json` and `minimal-install-audit.json` record versions and installed module origins.

MkDocs emitted an upstream Material advisory and an INFO notice about candidate-validation.md not being in nav; strict build exited successfully with no project warning/error.
