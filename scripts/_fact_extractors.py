"""Shared fact extractors for doc-sync.

Importable by scripts/sync_docs.py. Uses pure string operations
(no imports of sqlseed internals) to avoid circular dependencies.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_quoted_key(line: str) -> str | None:
    """Extract the first quoted key from a line like '  "name": ...'."""
    first_q = line.find('"')
    if first_q == -1:
        return None
    second_q = line.find('"', first_q + 1)
    if second_q == -1:
        return None
    return line[first_q + 1 : second_q]


def get_generator_types() -> set[str]:
    """Extract generator type names from _GENERATOR_MAP."""
    code = _read(ROOT / "src" / "sqlseed" / "generators" / "_dispatch.py")
    names: set[str] = set()
    marker = '"_gen_'
    for line in code.splitlines():
        idx = line.find(marker)
        if idx == -1:
            continue
        key = _extract_quoted_key(line[:idx])
        if key:
            names.add(key)
    return names


def get_exact_match_rules() -> dict[str, str]:
    """Extract exact match rules from mapper."""
    code = _read(ROOT / "src" / "sqlseed" / "core" / "mapper.py")
    rules: dict[str, str] = {}
    in_dict = False
    for line in code.splitlines():
        stripped = line.strip()
        if "EXACT_MATCH_RULES" in line:
            in_dict = True
            continue
        if in_dict:
            if stripped.startswith("}"):
                break
            parts = stripped.split('": "')
            if len(parts) == 2:
                key = parts[0].lstrip('" ')
                value = parts[1].rstrip('",')
                rules[key] = value
    return rules


def get_pattern_match_rules() -> list[tuple[str, ...]]:
    """Extract pattern match rules from mapper.

    Counts rules by detecting the regex pattern (r"...") which every
    rule has exactly one of. Handles multi-line tuples.
    """
    code = _read(ROOT / "src" / "sqlseed" / "core" / "mapper.py")
    rules: list[tuple[str, ...]] = []
    in_tuple = False
    for line in code.splitlines():
        stripped = line.strip()
        if "PATTERN_MATCH_RULES" in line and "=" in line:
            in_tuple = True
            continue
        if not in_tuple:
            continue
        if stripped == ")":
            break
        idx = stripped.find('r"')
        if idx != -1:
            second_q = stripped.find('"', idx + 2)
            if second_q != -1:
                rules.append((stripped[idx + 2 : second_q],))
    return rules


def get_safe_functions() -> set[str]:
    """Extract function names from ExpressionEngine.SAFE_FUNCTIONS."""
    code = _read(ROOT / "src" / "sqlseed" / "core" / "expression.py")
    marker = "SAFE_FUNCTIONS"
    start = code.find(marker)
    if start == -1:
        return set()
    brace_start = code.find("{", start)
    if brace_start == -1:
        return set()
    brace_end = code.find("}", brace_start)
    body = code[brace_start + 1 : brace_end] if brace_end != -1 else code[brace_start + 1 :]
    funcs: set[str] = set()
    for line in body.splitlines():
        key = _extract_quoted_key(line)
        if key and key[0].islower() and not key.isdigit():
            funcs.add(key)
    return funcs


def get_enum_name_patterns() -> list[str]:
    """Extract enum name patterns from enrichment."""
    code = _read(ROOT / "src" / "sqlseed" / "core" / "enrichment.py")
    patterns: list[str] = []
    in_list = False
    for line in code.splitlines():
        stripped = line.strip()
        if "ENUM_NAME_PATTERNS" in line and "=" in line:
            in_list = True
            continue
        if not in_list:
            continue
        if stripped == "]":
            break
        first_q = stripped.find('"')
        if first_q != -1:
            second_q = stripped.find('"', first_q + 1)
            if second_q != -1:
                patterns.append(stripped[first_q + 1 : second_q])
    return patterns


def get_hook_names() -> set[str]:
    """Extract hook function names from hookspecs."""
    code = _read(ROOT / "src" / "sqlseed" / "plugins" / "hookspecs.py")
    hooks: set[str] = set()
    marker = "def sqlseed_"
    for line in code.splitlines():
        idx = line.find(marker)
        if idx == -1:
            continue
        rest = line[idx + len(marker) :]
        name = "sqlseed_"
        for ch in rest:
            if ch.isalnum() or ch == "_":
                name += ch
            else:
                break
        hooks.add(name)
    return hooks


def _extract_func_name(def_line: str) -> str | None:
    """Extract function name from a 'def ...' or 'async def ...' line."""
    prefix = "async def " if def_line.startswith("async def ") else "def "
    if not def_line.startswith(prefix):
        return None
    rest = def_line[len(prefix) :]
    name = ""
    for ch in rest:
        if ch.isalnum() or ch == "_":
            name += ch
        else:
            break
    return name if name else None


def get_mcp_tool_names() -> list[str]:
    """Extract MCP tool function names from server.py."""
    code = _read(ROOT / "plugins" / "mcp-server-sqlseed" / "src" / "mcp_server_sqlseed" / "server.py")
    tools: list[str] = []
    lines = code.splitlines()
    for i, line in enumerate(lines):
        if "@mcp.tool()" not in line:
            continue
        for j in range(i + 1, min(i + 5, len(lines))):
            def_line = lines[j].strip()
            if def_line.startswith("def ") or def_line.startswith("async def "):
                name = _extract_func_name(def_line)
                if name:
                    tools.append(name)
                break
    return tools


def collect_all_facts() -> dict[str, object]:
    """Collect all code-derived facts as a dictionary."""
    return {
        "generator_count": len(get_generator_types()),
        "exact_match_rule_count": len(get_exact_match_rules()),
        "pattern_match_rule_count": len(get_pattern_match_rules()),
        "safe_function_count": len(get_safe_functions()),
        "enum_name_pattern_count": len(get_enum_name_patterns()),
        "hook_count": len(get_hook_names()),
        "mcp_tool_names": get_mcp_tool_names(),
    }
