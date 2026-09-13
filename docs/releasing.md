# Publishing and verifying a release

Source, documentation and PyPI are separate deliveries. A successful merge updates
the repository; the Pages workflow deploys documentation after main CI succeeds.
The PyPI description comes from each distribution's README metadata, so editing
GitHub alone does not update a previously uploaded package. See the
[PyPA README guide](https://packaging.python.org/en/latest/guides/making-a-pypi-friendly-readme/).

## Prepare the five packages

The five-package layout starts with 0.2.4. Release Core (`sqlseed`), CLI
(`sqlseed-cli`), AI (`sqlseed-ai`), MCP (`mcp-server-sqlseed`) and Web
(`sqlseed-web`) from the same reviewed commit and version tag. Do not combine
0.2.3 Core with the new plugins. The [migration guide](migration.md) covers the
changed entry points and compatibility limits.

Before publishing:

1. Merge the reviewed changes through all required checks. Follow the root
   [release checklist](https://github.com/sunbos/sqlseed/blob/main/CLAUDE.md#release-checklist),
   including both changelogs and the local mutation gate.
2. Build all five wheels and sdists. Run `twine check --strict` on all ten
   artifacts. Check that the package names and versions match, each archive
   includes the AGPL license text, and metadata contains the correct README,
   dependencies and Documentation URL.
3. Install the artifact set in fresh environments and run the distribution
   checks below. Check the built documentation and README links, including
   their rendered presentation. A metadata check alone does not check layout.
4. Confirm the publishing identity for all five projects: owner `sunbos`,
   repository `sqlseed`, workflow file `publish.yml`. Core, AI and MCP use the
   GitHub environment `pypi`; CLI uses `pypi-cli`; Web uses `pypi-web`. Existing
   projects need matching Trusted Publishers; a first publication can use a
   pending publisher. The distinct CLI/Web environments allow separate pending
   publishers for their first releases. A public project returning 404 does not
   reveal whether one is configured. See [PyPI's setup instructions](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).
5. Select the release version and obtain the maintainer's release approval.
   Push the reviewed commit before its `v<version>` tag, then create the GitHub
   release. Publishing is a separate operation from documentation review.

The [publish workflow](https://github.com/sunbos/sqlseed/blob/main/.github/workflows/publish.yml)
tests Python 3.10, 3.12 and 3.13, requires a `v` tag, builds the five packages,
checks their metadata and wheel versions, then publishes each project's wheel
and sdist in its own Trusted Publishing job. Jobs can succeed independently;
this is not an atomic five-package transaction.
Keep the workflow run, commit, tag and artifact hashes with the release record.
If a publish fails partway through, inspect which files reached PyPI before
retrying the same release. Its `skip-existing` setting does not prove all five
packages were uploaded successfully.

## Validate installed artifacts before release

Use a fresh virtual environment outside the checkout. Install all five wheel
paths in one `pip install` invocation, requesting the AI wheel's `[mcp]` extra
to enable the independent AI MCP server. From outside the checkout, with
`PYTHONPATH` unset, run the scripts from the reviewed repository:

```bash
python -m pip check
python /path/to/sqlseed/scripts/check_wheel_install.py
python /path/to/sqlseed/scripts/check_public_entrypoints.py 0.2.4
```

Replace `0.2.4` with the exact version under test. Repeat in a fresh environment
containing only Core and Web, running `check_wheel_install.py
--without-optional-components`. Also install the five sdists together in a
third environment and repeat the full checks. Never present a development
version or a local version override as an already published release.

## Verify from public PyPI after publication

Run the following from the reviewed checkout after all five projects have the
exact version. A Linux runner with Python 3.12 is a useful reference environment;
the Bash script also supports macOS. Set `PYTHON_BIN` to the desired interpreter.
After all five upload jobs succeed, the publish workflow runs this check on
Linux with Python 3.12 and retains the `public-pypi-acceptance` artifact. Use the
same command below to repeat it locally or on another supported platform.

```bash
PYTHON_BIN=python3.12 bash scripts/verify_pypi_release.sh 0.2.4
```

The script uses the production PyPI index, creates disposable environments,
ignores local package paths and saves the package metadata and installation
reports. It checks the exact public version and its wheel/sdist availability,
then tests full wheel, minimal Core/Web and full sdist installations. Third-party
dependencies may build from source when a platform wheel is unavailable; that
requires the dependency's build toolchain.

The installed-package checks cover:

- Imports from the environment's `site-packages`, matching package versions and
  the separation of the Core and CLI entry points.
- Real SQLite generation through Core, CLI and the offline MCP server, including
  expected row counts and preservation of unrelated rows.
- Web startup on a temporary port, assets, preview and generation through HTTP.
- Discovery of the four tools from the separate AI MCP server. Discovery does
  not invoke a model or prove that an LLM backend is reachable.

Open all five PyPI project pages after upload. Check the selected version,
rendered descriptions, Documentation links, license and downloadable files.
Compare the uploaded file hashes with the retained build artifacts. Verify the
Pages deployment uses the reviewed main commit and that the installation,
migration and API pages load correctly.

Keep real PostgreSQL and real LLM acceptance evidence separate. The public
installation script uses SQLite and does not claim either of those integrations
has been tested. A failed public installation or broken entry point is a release
failure even if the local wheel checks passed.
