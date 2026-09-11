# CI dependency maintenance

CI installs third-party dependencies from `requirements-ci.txt`, a universal
Python 3.10+ resolution with exact versions and distribution hashes. Pip accepts
wheels for external packages except the explicitly named source-only
`glob2==0.7` and `mutmut==2.5.1`. The shared `install-ci-deps` action first installs
hash-locked setuptools/wheel from `requirements-bootstrap.txt`, then builds
these two hash-verified source archives with `--use-pep517 --no-build-isolation`. Other
external packages cannot fall back to source builds. The five local candidates are then
installed together with `--no-deps --no-build-isolation`, followed by `pip check`.
This keeps an unpublished candidate requirement out of the public index and
fails when package metadata needs a dependency absent from the lock.

The universal resolution does not guarantee binary distribution availability on
every architecture. The full CI matrix targets Linux x86_64, macOS ARM64 and
Windows x86_64. On macOS Intel, cryptography 49 and later no longer publish wheels;
the full CI lock therefore intentionally fails its binary-only policy there.
Do not downgrade cryptography to regain an obsolete wheel or enable unrestricted
source builds. The Core/Web-only lock does not include cryptography. This
limitation concerns the complete CI tool environment, not Core/Web runtime support.

The package job still builds **sdist, then wheel from that sdist** for every
package. `build --no-isolation` uses the locked hatchling/hatch-vcs environment;
it does not skip the source archive. Locally built wheels are trusted outputs of
the checked-out revision and install with `--no-deps`. They are not downloaded
third-party distributions and are not assigned precomputed hashes.

`requirements-minimal.txt` contains only Core + Web runtime dependencies,
constrained to the CI versions. Its separate fresh environment verifies missing
optional component behavior without accidentally installing AI, CLI, MCP,
Mimesis or PostgreSQL support. Neither file limits end users' package versions.

Regenerate from the repository root with uv:

```sh
uv pip compile .github/requirements-ci.in --universal --python-version 3.10 --generate-hashes --no-emit-package sqlseed --no-emit-package sqlseed-cli --no-emit-package sqlseed-ai --no-emit-package mcp-server-sqlseed --no-emit-package sqlseed-web --output-file .github/requirements-ci.txt
uv pip compile .github/requirements-bootstrap.in --constraints .github/requirements-ci.txt --universal --python-version 3.10 --generate-hashes --output-file .github/requirements-bootstrap.txt
uv pip compile .github/requirements-minimal.in --constraints .github/requirements-ci.txt --universal --python-version 3.10 --generate-hashes --no-emit-package sqlseed --no-emit-package sqlseed-web --output-file .github/requirements-minimal.txt
```

Use `--upgrade` deliberately when updating dependencies. Review all lock diffs and
run the full OS/Python CI matrix and package job. Maintain the existing three
`uv.lock` files separately when project manifests change; these CI exports do
not replace those package development locks.

The temporary CI-only `anyio<4.15` bound keeps Starlette 1.6.0's TestClient on
its compatible API. AnyIO 4.15 began warning about the alias TestClient uses;
[Starlette's fix](https://github.com/Kludex/starlette/pull/3498) is merged but not
released as of 2026-09-11. Remove the bound when a fixed Starlette release is
available, regenerate, and verify imports/tests with deprecations treated as
errors. No warning filters or third-party source patches are used.
