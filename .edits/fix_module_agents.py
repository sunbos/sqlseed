"""Fix module-level AGENTS.md files (items 10-14 of the fix list)."""
from pathlib import Path

CHANGED = []


def fix(path: str, pairs: list[tuple[str, str]]) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    orig = text
    for old, new in pairs:
        if old not in text:
            raise SystemExit(f"PATTERN NOT FOUND in {path}:\n{old[:120]}")
        text = text.replace(old, new, 1)
    if text != orig:
        p.write_text(text, encoding="utf-8")
        CHANGED.append(path)


# ── 10. src/sqlseed/AGENTS.md: core file count 19 -> 22 ──
fix(
    "/tmp/wt-contract/src/sqlseed/AGENTS.md",
    [
        (
            "├── core/             # Orchestration engine: orchestrator, mapper, schema, constraints, DAG, enrichment, transform, stream (19 files)",
            "├── core/             # Orchestration engine: orchestrator, mapper, schema, constraints, DAG, enrichment, transform, stream (22 files)",
        ),
    ],
)

# ── 11. src/sqlseed/core/AGENTS.md ──
fix(
    "/tmp/wt-contract/src/sqlseed/core/AGENTS.md",
    [
        # STRUCTURE: add check_parser.py / schema_fallback.py / features.py
        (
            "├── mapper.py            # ColumnMapper 9-level strategy chain\n├── schema.py            # SchemaInferrer — column info, indexes, distribution",
            "├── mapper.py            # ColumnMapper 9-level strategy chain\n"
            "├── schema.py            # SchemaInferrer — column info, indexes, distribution\n"
            "├── check_parser.py      # CheckConstraintParser + ParsedCheck — single-column CHECK → generator hints\n"
            "├── schema_fallback.py   # SchemaFallbackGenerator — pure schema-semantics fallback, zero business logic\n"
            "├── features.py          # Normalized structural features for cross-DB schema analysis",
        ),
        # WHERE TO LOOK: __init__.py export list
        (
            "| Public API exports | `__init__.py` | Exports DataOrchestrator, ColumnMapper, GeneratorSpec, DataStream, RelationResolver, GenerationResult, SchemaInferrer |",
            "| Public API exports | `__init__.py` | Exports DataOrchestrator, ColumnMapper, GeneratorSpec, DataStream, RelationResolver, GenerationResult, SchemaInferrer, CheckConstraintParser, ParsedCheck, SchemaFallbackGenerator |",
        ),
        # WHERE TO LOOK: add rows after "Add schema info"
        (
            "| Add schema info | `schema.py` | SchemaInferrer.get_column_info() |",
            "| Add schema info | `schema.py` | SchemaInferrer.get_column_info() |\n"
            "| Parse CHECK constraints | `check_parser.py` | CheckConstraintParser, ParsedCheck |\n"
            "| Schema-only fallback | `schema_fallback.py` | SchemaFallbackGenerator — called when mapping yields nothing |",
        ),
    ],
)

# ── 12. src/sqlseed/database/AGENTS.md ──
fix(
    "/tmp/wt-contract/src/sqlseed/database/AGENTS.md",
    [
        (
            "├── _protocol.py           # DatabaseAdapter protocol, ColumnInfo, ForeignKeyInfo, IndexInfo",
            "├── _protocol.py           # DatabaseAdapter protocol, ColumnInfo, ForeignKeyInfo, IndexInfo, CheckConstraintInfo",
        ),
        (
            "├── _helpers.py            # fetch_index_info, fetch_sample_rows, apply_bulk_optimize/restore",
            "├── _helpers.py            # fetch_index_info, fetch_sample_rows, batch_insert_rows, apply_bulk_optimize/restore",
        ),
    ],
)

# ── 13. src/sqlseed/_utils/AGENTS.md ──
fix(
    "/tmp/wt-contract/src/sqlseed/_utils/AGENTS.md",
    [
        (
            "| `paths.py` | `get_cache_dir(subdir)` platform-standard cache directory (macOS/Linux/Windows), `SQLSEED_CACHE_DIR` environment variable takes highest priority, shared by SnapshotManager and AiConfigRefiner |",
            "| `paths.py` | `get_cache_dir(subdir)` platform-standard cache directory (macOS/Linux/Windows), `SQLSEED_CACHE_DIR` environment variable takes highest priority, shared by SnapshotManager and AiConfigRefiner; `validate_db_target()` (extension/existence check for file paths, URL pass-through) and `validate_table_name()` (membership check against existing tables) — shared by both MCP server packages (`mcp-server-sqlseed` and `sqlseed-ai[mcp]`) |",
        ),
    ],
)

# ── 14. src/sqlseed/generators/AGENTS.md ──
fix(
    "/tmp/wt-contract/src/sqlseed/generators/AGENTS.md",
    [
        (
            "35 generators across 3 providers: base (type-routing only, no real data), faker (required), mimesis (optional).",
            "35 generators across 3 providers: base (zero-dep fallback, synthesizes values via counter + seeded RNG), faker (required), mimesis (optional).",
        ),
        (
            "├── base_provider.py     # BaseProvider — type-routing only (no real data generation); delegates to faker/mimesis",
            "├── base_provider.py     # BaseProvider — zero-dep fallback; synthesizes placeholder data via counter + seeded RNG (no hardcoded lists)",
        ),
    ],
)

print("\n".join(CHANGED))
