# sqlseed

**Declarative SQLite and PostgreSQL test data generation.**

Generate test data from existing database schemas, YAML/JSON rules, or the Python
API. The offline Core provides schema inference, 36 generators, foreign-key
handling, expressions, and pluggy hooks. CLI, AI, MCP, and Web are separate packages.

## Documentation version and installation

These pages describe the five-package workbench on `main`, targeting the 0.2.4
release series. They also cover changes beyond the older combined 0.2.3 packages.
Merging source and deploying these pages do not publish packages to PyPI. At the
2026-09-13 review, PyPI had Core/AI/MCP 0.2.3 and no CLI/Web distributions; consult
the [release list](https://github.com/sunbos/sqlseed/releases) for later releases.

Until a compatible five-package release is available, install from one source
checkout or one successful CI artifact. See the [upgrade guide](migration.md) for
wheel installation and compatibility details. From the repository root:

```bash
python -m pip install -e '.[mimesis,postgres]' -e ./plugins/sqlseed-cli -e './plugins/sqlseed-ai[mcp]' -e ./plugins/mcp-server-sqlseed -e ./plugins/sqlseed-web
python -m pip check
```

For offline Python use alone, install `python -m pip install -e '.[mimesis]'`.
Choose the [installation guide](guide.md#installation) for a smaller package set.

## Quick start

Prepare an existing database and its tables first. The repository includes a
small demo:

```bash
python examples/build_demo_db.py
sqlseed fill examples/sqlseed_demo.db -t organizations -n 10
sqlseed preview examples/sqlseed_demo.db -t members -n 5
sqlseed fill examples/sqlseed_demo.db -t members -n 100
sqlseed inspect examples/sqlseed_demo.db --show-mapping
```

```python
from sqlseed import fill

# The parent organizations must already be populated, as in the CLI example.
result = fill("examples/sqlseed_demo.db", table="members", count=100)
print(result.count, result.errors)
```

The same public API accepts PostgreSQL URLs through `url=`, with the `postgres`
extra installed. Supported constraints differ by database and entry point;
consult [support and maintenance](maintainable-release.md) before using complex
foreign keys or replacing existing data. A failed run can retain earlier
committed batches, so check both `count` and `errors`.

## Choose an entry point

| Entry point | Package | Guide |
| --- | --- | --- |
| Python API and offline rules | `sqlseed` | [API reference](api.md) |
| Terminal generation and inspection | `sqlseed-cli` | [CLI reference](guide.md#cli-reference) |
| Browser workbench | `sqlseed-web` | [Web workbench](web-workbench.md) |
| Optional model suggestions and repair | `sqlseed-ai` | [AI guide](guide.md#ai-plugin) |
| Rule-driven MCP tools | `mcp-server-sqlseed` | [MCP setup](guide.md#mcp-server) |

AI MCP tools run in the separate `mcp-server-sqlseed-ai` process supplied by
`sqlseed-ai[mcp]`. Accepted rules can be executed offline.

For internal design, see [architecture](architecture.md). For a complete example
with constraints, failure diagnosis, and replay, see the
[project walkthrough](project-showcase.md).
