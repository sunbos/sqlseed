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

The full CI matrix targets Linux x86_64, native macOS ARM64 and Intel x86_64,
and Windows x86_64. The universal resolution does not guarantee wheel
availability on every architecture. On Intel macOS, cryptography 49 and later
no longer publish wheels. Only on that platform, `install-ci-deps` also permits
the hash-locked `cryptography` source archive and installs its Python build
requirements from `requirements-macos-build.txt`. Native Rust, Xcode command-line
tools and Homebrew OpenSSL 3 must be available; the build uses
`OPENSSL_DIR="$(brew --prefix openssl@3)"`. ARM64 Macs retain the normal wheel
policy. No package version is downgraded and other source-build exceptions are
unchanged. The Core/Web-only lock does not include cryptography.

For the same full locked environment on an Intel Mac, activate a new virtualenv,
install Xcode command-line tools and `brew install rust openssl@3`, then run:

```sh
python -m pip install --require-hashes --only-binary :all: -r .github/requirements-bootstrap.txt
python -m pip install --require-hashes --only-binary :all: -r .github/requirements-macos-build.txt
export OPENSSL_DIR="$(brew --prefix openssl@3)"
python -m pip install --require-hashes --only-binary :all: --no-binary glob2,mutmut,cryptography --no-build-isolation --use-pep517 -r .github/requirements-ci.txt
python -m pip install --no-deps --no-build-isolation -e '.[all,dev,docs]' -e './plugins/sqlseed-cli' -e './plugins/sqlseed-ai[dev]' -e './plugins/mcp-server-sqlseed' -e './plugins/sqlseed-web[dev]'
python -m pip check
```

The build requirements mirror the locked cryptography release's
`build-system.requires`; reassess them when upgrading that release. Upstream
no longer tests Intel macOS, so our native CI and installation checks establish
sqlseed's coverage; source compilation alone is not a compatibility guarantee.
See [cryptography installation](https://cryptography.io/en/latest/installation/)
and [macOS setup](../docs/macos.md) for user installation and architecture details.

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
uv pip compile .github/requirements-macos-build.in --universal --python-version 3.10 --generate-hashes --output-file .github/requirements-macos-build.txt
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
