"""Fix sqlseed-ai AGENTS.md files (items 15-16 of the fix list)."""
from pathlib import Path

CHANGED = []


def fix(path: str, pairs: list[tuple[str, str]]) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    orig = text
    for old, new in pairs:
        if old not in text:
            raise SystemExit(f"PATTERN NOT FOUND in {path}:\n{old[:150]}")
        text = text.replace(old, new, 1)
    if text != orig:
        p.write_text(text, encoding="utf-8")
        CHANGED.append(path)


# ── 15. plugins/sqlseed-ai/AGENTS.md: repair/ add models.py ──
fix(
    "/tmp/wt-contract/plugins/sqlseed-ai/AGENTS.md",
    [
        (
            "    │   ├── executor.py   # applies strategies by fix_hint dispatch\n    │   └── pipeline.py   # chains strategies",
            "    │   ├── executor.py   # applies strategies by fix_hint dispatch\n"
            "    │   ├── models.py     # AppliedFix, RepairResult\n"
            "    │   └── pipeline.py   # chains strategies",
        ),
    ],
)

# ── 16. plugins/sqlseed-ai/src/sqlseed_ai/AGENTS.md ──
fix(
    "/tmp/wt-contract/plugins/sqlseed-ai/src/sqlseed_ai/AGENTS.md",
    [
        # Key Files: add 5 v4 subsystem packages
        (
            "| `analyzer/_json_parser.py` | `JsonParserMixin` — JSON response parsing and analysis entry points |\n| `_prompts.py` |",
            "| `analyzer/_json_parser.py` | `JsonParserMixin` — JSON response parsing and analysis entry points |\n"
            "| `contracts/` | v4 Layer 1 — sparse contract matrix + resolver (known-bad generator/type/constraint combos, closed set) |\n"
            "| `validator/` | v4 Layer 2 — `FastValidator` (single-column + cross-column validators, dialect error parsing) |\n"
            "| `repair/` | v4 Layer 3 — stateless repair engine (pure functions in `REPAIR_STRATEGIES`, open for extension) |\n"
            "| `healer/` | v4 Layer 4 — 4-level LLM heal architecture (subgraph → column → compact → degrade) |\n"
            "| `auto_heal/` | v4 Layer 5 — `AutoHealOrchestrator` top-level entry (ai-analyze default path) |\n"
            "| `_prompts.py` |",
        ),
        # SQLSEED_AI_TIMEOUT default 60.0 -> 0 (auto-resolve)
        (
            "| `SQLSEED_AI_TIMEOUT` | `timeout` | Default 60.0 |",
            "| `SQLSEED_AI_TIMEOUT` | `timeout` | Default 0 (auto-resolve via `resolve_timeout()` per backend) |",
        ),
        # WHERE TO LOOK hook list: actual 4 hookimpls
        (
            "| Modify hook implementations | `__init__.py` | `sqlseed_ai_analyze_table`, `sqlseed_pre_generate_templates` |",
            "| Modify hook implementations | `__init__.py` | `sqlseed_ai_analyze_table`, `sqlseed_apply_ai_suggestions`, `sqlseed_transform_row`, `sqlseed_pre_generate_templates` |",
        ),
        # Working In This Directory hook list: actual 4 hookimpls
        (
            "- `AISqlseedPlugin` implements `hookimpl` for `sqlseed_ai_analyze_table` (full-table analysis) and `sqlseed_pre_generate_templates` (per-column value generation for non-simple columns). The `sqlseed_apply_ai_suggestions` hook (high-level AI mediation) is implemented in `ai_mediator.py` (Phase C, moved from core). It does NOT implement `sqlseed_register_providers` or `sqlseed_register_column_mappers`.",
            "- `AISqlseedPlugin` implements 4 `hookimpl`s in `__init__.py`: `sqlseed_ai_analyze_table` (full-table analysis), `sqlseed_apply_ai_suggestions` (high-level AI mediation — delegates to `ai_mediator.apply_ai_suggestions`, Phase C moved from core), `sqlseed_transform_row` (defensive ISO-date-string → `datetime.date` fallback for mis-configured DATE columns), and `sqlseed_pre_generate_templates` (per-column value generation for non-simple columns). It does NOT implement `sqlseed_register_providers` or `sqlseed_register_column_mappers`.",
        ),
    ],
)

print("\n".join(CHANGED))
