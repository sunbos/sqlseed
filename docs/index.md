# sqlseed

**Declarative SQLite and PostgreSQL test data generation.**

Generate test data from existing database schemas, YAML/JSON rules, or the Python
API. The offline Core provides schema inference, 36 generators, foreign-key
handling, expressions, and pluggy hooks. CLI, AI, MCP, and Web are separate packages.

## Documentation version and installation

These pages cover the five-package layout introduced in 0.2.4. Core, CLI, AI,
MCP, and Web are separate distributions; the older 0.2.3 packages use different
entry points. See the [upgrade guide](migration.md) for compatibility details.

For the 0.2.4 release, use a fresh Python 3.10+ environment and install the package
set you need. This complete installation includes Mimesis, PostgreSQL support,
and both MCP servers:

```bash
python -m pip install 'sqlseed[mimesis,postgres]==0.2.4' 'sqlseed-cli==0.2.4' 'sqlseed-ai[mcp]==0.2.4' 'mcp-server-sqlseed==0.2.4' 'sqlseed-web==0.2.4'
python -m pip check
```

For offline Python use alone, install `python -m pip install 'sqlseed[mimesis]==0.2.4'`.
Choose the [installation guide](guide.md#installation) for a smaller package set
or a source checkout. Package availability and release verification are tracked
separately in the [release list](https://github.com/sunbos/sqlseed/releases) and
[release guide](releasing.md).

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
