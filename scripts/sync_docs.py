"""Sync markdown documentation facts with source code.

Scans markdown files for <!-- BEGIN:AUTO-GENERATED:<name> --> markers
and replaces the content between BEGIN and END with the current value
extracted from source code.

Usage:
    python scripts/sync_docs.py           # Update markers in-place
    python scripts/sync_docs.py --check   # Exit 1 if any marker is stale
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Import after sys.path manipulation — cannot be at module top.
# pylint: disable=wrong-import-position
from _fact_extractors import collect_all_facts

ROOT = Path(__file__).resolve().parent.parent

MARKER_RE = re.compile(
    r"(<!-- BEGIN:AUTO-GENERATED:(\S+) -->)"
    r"(.*?)"
    r"(<!-- END:AUTO-GENERATED:\2 -->)",
    re.DOTALL,
)

# Map marker names to formatted output (just the number, so it works
# in both English and Chinese contexts)
FACT_FORMATTERS: dict[str, object] = {
    "generator-count": lambda f: f"{f['generator_count']}",
    "exact-match-rule-count": lambda f: f"{f['exact_match_rule_count']}",
    "pattern-match-rule-count": lambda f: f"{f['pattern_match_rule_count']}",
    "safe-function-count": lambda f: f"{f['safe_function_count']}",
    "enum-name-pattern-count": lambda f: f"{f['enum_name_pattern_count']}",
    "hook-count": lambda f: f"{f['hook_count']}",
    "mcp-tool-names": lambda f: ", ".join(f["mcp_tool_names"]),  # type: ignore[arg-type]
}


def find_markdown_files() -> list[Path]:
    """Find all markdown files in the project (excluding build/cache dirs)."""
    exclude_dirs = {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "site",
        "superpowers",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
    }
    files: list[Path] = []
    for p in ROOT.rglob("*.md"):
        if any(part in exclude_dirs for part in p.parts):
            continue
        files.append(p)
    return files


def sync_file(path: Path, facts: dict[str, object], check_only: bool) -> list[str]:
    """Sync markers in a single file. Returns list of changed marker names."""
    text = path.read_text(encoding="utf-8")
    changes: list[str] = []

    def replacer(match: re.Match[str]) -> str:
        begin_tag = match.group(1)
        name = match.group(2)
        old_content = match.group(3)
        end_tag = match.group(4)
        formatter = FACT_FORMATTERS.get(name)
        if formatter is None:
            print(f"WARNING: Unknown marker '{name}' in {path} — skipping")
            return match.group(0)  # Unknown marker, leave unchanged
        new_content = formatter(facts)
        if new_content != old_content:
            changes.append(name)
        return begin_tag + new_content + end_tag

    new_text = MARKER_RE.sub(replacer, text)
    if new_text != text and not check_only:
        path.write_text(new_text, encoding="utf-8")
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync markdown docs with code facts")
    parser.add_argument("--check", action="store_true", help="Exit 1 if any marker is stale")
    args = parser.parse_args()

    facts = collect_all_facts()
    all_changes: list[tuple[Path, list[str]]] = []

    for md_file in find_markdown_files():
        changes = sync_file(md_file, facts, args.check)
        if changes:
            all_changes.append((md_file, changes))

    if all_changes:
        for path, names in all_changes:
            rel = path.relative_to(ROOT)
            for name in names:
                if args.check:
                    print(f"STALE: {rel} marker '{name}' is out of date")
                else:
                    print(f"UPDATED: {rel} marker '{name}'")
        total = sum(len(n) for _, n in all_changes)
        if args.check:
            print(f"\n{total} stale marker(s) found.")
            print("Run `python scripts/sync_docs.py` to update.")
            return 1
        print(f"\n{total} marker(s) updated.")
    else:
        print("All markers are up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
