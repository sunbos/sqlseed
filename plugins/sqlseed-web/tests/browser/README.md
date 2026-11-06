# Browser smoke test

Run from the repository root after the normal local Core/Web development install:

```sh
node --test plugins/sqlseed-web/tests/browser/test_workbench.cjs
```

Requires Node 24, Python, and Google Chrome (`CHROME_BIN` can select an installed
Chromium executable; `PYTHON` can select the project virtualenv's Python).
CI uses the preinstalled Chrome on `ubuntu-24.04` and the official Node 24
runtime of the SHA-pinned `actions/github-script`. The actual browser version
is printed in the job log. There is no npm install or additional Python dependency;
the existing hash-locked CI installation remains unchanged.

This is a separate real-browser job, not part of the lightweight
`node --test plugins/sqlseed-web/tests/test_*.cjs` DOM regression command.
The test uses Chrome's private DevTools pipe, native mouse/keyboard input,
the app's real HTTP server and a freshly created synthetic SQLite database.
It checks:

- Loading the actual ES modules and dismissing/reopening the connection dialog
- Connecting through the UI and selecting a real table with a three-row count
- Rendering preview samples while the database remains empty
- Cancelling a validated generation plan without writing rows
- Confirming generation, checking actual committed counts and CHECK constraints
- Restoring the persisted successful run after reload and returning to the workbench
- Absence of uncaught JavaScript exceptions

The harness owns server/browser startup and cleanup, uses an OS-assigned
loopback port and a fresh browser profile, isolates settings/workspace/cache,
and does not inherit API keys or use a user's database. Browser sandboxing stays
enabled. Individual commands, waits, the test, subprocess, and CI job have
bounded timeouts. Missing Chrome fails the job rather than silently skipping it.

Failures save a screenshot, rendered HTML and process/error logs to
`BROWSER_ARTIFACTS` (default: `browser-artifacts`). CI retains these synthetic-data
artifacts for seven days. Temporary databases and profiles are removed, never
uploaded. This smoke test does not claim cross-browser, pixel-perfect, real-LLM,
PostgreSQL, or installed-wheel coverage; those remain separate checks.
