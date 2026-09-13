# Upgrading to the five-package workbench

[中文](migration.zh-CN.md)

The workbench on `main` replaces the older combined Core/CLI/MCP installation with five packages and targets the 0.2.4 release series. Merging its source into `main` does not publish these packages to PyPI. Until a compatible release is published, use one source checkout or the artifacts from one successful CI run. The [installation guide](guide.md#installation) separates these source instructions from commands for a future compatible release.

## Install a compatible set

Create a fresh virtual environment and install the five wheels from the same CI artifact together:

```bash
python -m venv .venv
# Activate the environment using your shell's activation command.
python -m pip install /path/to/candidate-wheels/*.whl
python -m pip check
```

For a source checkout, supply Core and the local plugins in the same resolution:

```bash
python -m pip install -e . -e ./plugins/sqlseed-cli -e './plugins/sqlseed-ai[mcp]' -e ./plugins/mcp-server-sqlseed -e ./plugins/sqlseed-web
python -m pip check
```

The candidate plugins require Core `>=0.2.4.dev0,<0.3`; their CLI/AI sibling dependencies use the same release series. Core 0.2.3 does not provide the interfaces required by these plugins. The upper bound prevents an unreviewed future minor version from being selected automatically. It does not promise that arbitrary development snapshots within the range are interchangeable: use a single artifact set.

Retain the Core extras used by your previous environment. The five ordinary wheels do not install the PostgreSQL driver or Mimesis. For source installation, replace `-e .` above with `-e '.[postgres,mimesis]'` when both are needed. For wheels, include the exact Core wheel path with `[postgres,mimesis]` appended in the same install command. A fresh environment without the PostgreSQL driver cannot connect to PostgreSQL; without Mimesis, the existing provider fallback behavior applies.

The CI run's `headSha` identifies the candidate source. A pull request artifact's name can use GitHub's synthetic merge commit instead, so check the run and the artifact together. Keep the previous environment and wheel set until migration is verified.

## Update entry points

| Existing usage | New entry point |
| --- | --- |
| Python `from sqlseed import fill, connect, preview` | Remains in Core; the existing public API is retained |
| `sqlseed` shell command installed with Core | Install `sqlseed-cli`; after release, `sqlseed[cli]` is also available as a convenience extra |
| Importing `sqlseed.cli` | Use the CLI package's supported command entry point; the old Core module has been removed |
| Core MCP with AI tools | Run a separate `mcp-server-sqlseed-ai` server from `sqlseed-ai[mcp]` |
| Local browser workflow | Run `sqlseed-web`, then open `http://127.0.0.1:8630` |

`mcp-server-sqlseed` now exposes `sqlseed_generate_yaml(db_path, table_name)` for offline rule generation and `sqlseed_execute_fill` for execution. The old AI arguments to `sqlseed_generate_yaml`, schema inspection tool and schema resource are removed. Update MCP client tool selections and saved calls accordingly.

The AI server provides `sqlseed_ai_generate_yaml`, `sqlseed_gemma4_analyze`, `sqlseed_gemma4_agent_fill`, and `sqlseed_list_gemma_models`. Configure its backend separately. Starting an MCP server is not proof that a real model is reachable; validate a small request before using it in an automated workflow.

## Verify saved configurations and data

Use a new test database or a disposable copy first. Check actual stored values as well as `GenerationResult.errors` and `count`. In normal Core batch mode, a later failure can leave earlier committed batches in place; a successful function return alone is insufficient. See [support and maintenance](maintainable-release.md).

Review JSON and date/time fields when migrating from SQLite's older untyped insertion path. JSON generator output is serialized JSON text and must retain its object/array/scalar meaning when stored in a JSON column. An ordinary TEXT column retains text semantics. Use explicit ISO date/time values or the corresponding Python date/time objects for temporal columns; invalid values are reported rather than silently repaired.

For a JSON string value, supply a serialized document such as `"hello"`, including its JSON quotes; bare `hello` is not valid JSON. Serialized `null` means JSON null, while SQLAlchemy's explicit `null()` retains SQL NULL semantics. Native Python objects are also supported. SQLite retains valid serialized text exactly so formatting changes cannot break text-based foreign-key equality. Internal JSON sampling and lookup preserve this serialized-document contract. Temporal binding follows the database column type; SQLite temporal columns do not preserve timezone offsets through SQLAlchemy. Use a TEXT column when exact original timestamp text is required.

Recheck self-referencing tables with composite primary keys and UNIQUE constraints using actual foreign-key and uniqueness queries. Keep explicit all-NULL rules when no parent relationship is desired. A nullable root is valid; not every row is guaranteed to receive a parent.

Web is a local workbench without multi-user authentication. PostgreSQL support has explicit limits, including composite and cross-schema foreign-key generation. Refer to the support document before migrating complex schemas or exposing a service to other users.

## Merge and release behavior

The public documentation deployment runs only after all main CI jobs succeed and builds the same commit. To retry a failed deployment, rerun the relevant main CI run. The standalone Pages workflow no longer has a separate push or manual trigger that bypasses those jobs.

PyPI publishing remains a separate release action, guarded by a version tag and matching versions across all five packages. A merged PR and a working documentation site are not a package release.
