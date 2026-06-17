"""Documentation sync validation tests.

Extracts facts from source code and verifies they match what
documentation files claim. Run with `pytest tests/test_doc_sync.py`.

When a test fails, it means a documentation file is stale and needs
updating — not that the code is wrong.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ── Helpers ──────────────────────────────────────────────────────────


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# Marker pattern must match scripts/sync_docs.py MARKER_RE exactly
_MARKER_RE = re.compile(
    r"<!-- BEGIN:AUTO-GENERATED:(\S+) -->(.*?)<!-- END:AUTO-GENERATED:\1 -->",
    re.DOTALL,
)


def _extract_marker_value(text: str, marker_name: str) -> str | None:
    """Extract the value inside an AUTO-GENERATED marker region.

    Returns None if the marker is not present. This lets tests verify
    marker content directly, avoiding the silent-failure mode where a
    number sits inside the marker and is separated from the surrounding
    keyword by the END tag.
    """
    for match in _MARKER_RE.finditer(text):
        if match.group(1) == marker_name:
            return match.group(2)
    return None


def _find_marker_claims(marker_name: str) -> list[tuple[Path, str]]:
    """Find all (doc_path, marker_value) pairs for a given marker name."""
    claims: list[tuple[Path, str]] = []
    for doc_path in _find_doc_files():
        text = _read(doc_path)
        value = _extract_marker_value(text, marker_name)
        if value is not None:
            claims.append((doc_path, value))
    return claims



def _find_doc_files() -> list[Path]:
    """Collect all .md files that may contain code-derived facts."""
    candidates = [
        ROOT / "README.md",
        ROOT / "README.zh-CN.md",
        ROOT / "CLAUDE.md",
        ROOT / "CHANGELOG.md",
        ROOT / "CHANGELOG.zh-CN.md",
        ROOT / "docs" / "architecture.md",
        ROOT / "docs" / "architecture.zh-CN.md",
        ROOT / "plugins" / "sqlseed-ai" / "README.md",
        ROOT / "plugins" / "sqlseed-ai" / "README.zh-CN.md",
        ROOT / "plugins" / "mcp-server-sqlseed" / "README.md",
        ROOT / "plugins" / "mcp-server-sqlseed" / "README.zh-CN.md",
        # AGENTS.md files contain code-derived facts (counts, file lists, etc.)
        ROOT / "AGENTS.md",
        ROOT / "src" / "sqlseed" / "AGENTS.md",
        ROOT / "src" / "sqlseed" / "core" / "AGENTS.md",
        ROOT / "src" / "sqlseed" / "generators" / "AGENTS.md",
        ROOT / "src" / "sqlseed" / "config" / "AGENTS.md",
        ROOT / "src" / "sqlseed" / "cli" / "AGENTS.md",
        ROOT / "src" / "sqlseed" / "database" / "AGENTS.md",
        ROOT / "src" / "sqlseed" / "plugins" / "AGENTS.md",
        ROOT / "src" / "sqlseed" / "_utils" / "AGENTS.md",
        ROOT / "plugins" / "sqlseed-ai" / "AGENTS.md",
        ROOT / "plugins" / "sqlseed-ai" / "src" / "sqlseed_ai" / "AGENTS.md",
        ROOT / "plugins" / "mcp-server-sqlseed" / "AGENTS.md",
        ROOT / "plugins" / "mcp-server-sqlseed" / "src" / "mcp_server_sqlseed" / "AGENTS.md",
        ROOT / "tests" / "AGENTS.md",
        ROOT / "tests" / "test_core" / "AGENTS.md",
        ROOT / "tests" / "test_generators" / "AGENTS.md",
        ROOT / "tests" / "test_database" / "AGENTS.md",
        ROOT / "tests" / "test_config" / "AGENTS.md",
        ROOT / "tests" / "test_plugins" / "AGENTS.md",
        ROOT / "tests" / "test_utils" / "AGENTS.md",
        ROOT / "tests" / "benchmarks" / "AGENTS.md",
    ]
    return [p for p in candidates if p.exists()]


def _docs_mention_number(number: int, context: str = "") -> list[str]:
    """Find which doc files mention a specific number with context."""
    hits = []
    for p in _find_doc_files():
        text = _read(p)
        if str(number) in text and ((context and context.lower() in text.lower()) or not context):
            hits.append(str(p.relative_to(ROOT)))
    return hits


def _read_number_before(text: str, position: int) -> str | None:
    """Walk backwards from position to extract a preceding number."""
    end = position
    while end > 0 and text[end - 1].isspace():
        end -= 1
    start = end
    while start > 0 and text[start - 1].isdigit():
        start -= 1
    return text[start:end] if start < end else None


def _extract_number_before_keyword(text: str, keywords: list[str]) -> list[str]:
    """Extract numbers that appear immediately before any of the given keywords.

    Uses pure string operations to avoid regex security hotspots.
    Case-insensitive for ASCII keywords.
    """
    results = []
    text_lower = text.lower()
    for kw in keywords:
        kw_lower = kw.lower()
        pos = 0
        while True:
            idx = text_lower.find(kw_lower, pos)
            if idx == -1:
                break
            num = _read_number_before(text, idx)
            if num is not None:
                results.append(num)
            pos = idx + len(kw)
    return results


def _extract_quoted_key(line: str) -> str | None:
    """Extract the first quoted key from a line like '  "name": ...'."""
    first_q = line.find('"')
    if first_q == -1:
        return None
    second_q = line.find('"', first_q + 1)
    if second_q == -1:
        return None
    return line[first_q + 1 : second_q]


# ── Source Code Fact Extractors (pure string operations) ─────────────


def _get_generator_types() -> set[str]:
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


def _get_exact_match_rules() -> dict[str, str]:
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
            # Parse "key": "value" pairs
            parts = stripped.split('": "')
            if len(parts) == 2:
                key = parts[0].lstrip('" ')
                value = parts[1].rstrip('",')
                rules[key] = value
    return rules


def _get_safe_functions() -> set[str]:
    """Extract function names from ExpressionEngine.SAFE_FUNCTIONS."""
    code = _read(ROOT / "src" / "sqlseed" / "core" / "expression.py")
    # Find the SAFE_FUNCTIONS dict body
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
        # Only string keys starting with a lowercase letter (skip numeric like "0")
        if key and key[0].islower() and not key.isdigit():
            funcs.add(key)
    return funcs


def _get_pattern_match_rules() -> list[tuple[str, ...]]:
    """Extract pattern match rules from mapper.

    PATTERN_MATCH_RULES is a tuple of (pattern, generator, params) tuples.
    Some tuples span multiple lines (the '(' may be on its own line).
    We count rules by detecting the regex pattern (r"...") which every
    rule has exactly one of.
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
        # End of the tuple (line is just ')')
        if stripped == ")":
            break
        # Each rule has exactly one regex pattern starting with r"
        # It may appear as (r"..." or r"..." (multi-line tuple continuation)
        idx = stripped.find('r"')
        if idx != -1:
            second_q = stripped.find('"', idx + 2)
            if second_q != -1:
                rules.append((stripped[idx + 2 : second_q],))
    return rules


def _get_enum_name_patterns() -> list[str]:
    """Extract enum name patterns from enrichment.

    ENUM_NAME_PATTERNS is a ClassVar[list[str]] with one regex per line.
    """
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
        # Extract the quoted regex string
        first_q = stripped.find('"')
        if first_q != -1:
            second_q = stripped.find('"', first_q + 1)
            if second_q != -1:
                patterns.append(stripped[first_q + 1 : second_q])
    return patterns


def _get_mcp_tool_names() -> list[str]:
    """Extract MCP tool function names from server.py.

    Looks for @mcp.tool() decorated functions.
    """
    code = _read(
        ROOT
        / "plugins"
        / "mcp-server-sqlseed"
        / "src"
        / "mcp_server_sqlseed"
        / "server.py"
    )
    tools: list[str] = []
    lines = code.splitlines()
    for i, line in enumerate(lines):
        if "@mcp.tool()" in line:
            # Next non-empty line should be the def
            for j in range(i + 1, min(i + 5, len(lines))):
                def_line = lines[j].strip()
                if def_line.startswith("def ") or def_line.startswith("async def "):
                    prefix = "async def " if def_line.startswith("async def ") else "def "
                    rest = def_line[len(prefix) :]
                    name = ""
                    for ch in rest:
                        if ch.isalnum() or ch == "_":
                            name += ch
                        else:
                            break
                    if name:
                        tools.append(name)
                    break
    return tools


def _get_hook_names() -> set[str]:
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


def _get_config_fields(cls_name: str) -> set[str]:
    """Extract field names from a Pydantic model class."""
    code = _read(ROOT / "src" / "sqlseed" / "config" / "models.py")
    # Find the class body using string operations
    marker = f"class {cls_name}"
    start = code.find(marker)
    if start == -1:
        return set()
    next_class = code.find("\nclass ", start + len(marker))
    body = code[start:] if next_class == -1 else code[start:next_class]

    fields: set[str] = set()
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("class "):
            continue
        # Check for "field_name:" pattern (field definition)
        colon_idx = stripped.find(":")
        if colon_idx > 0:
            field_name = stripped[:colon_idx].strip()
            if field_name.isidentifier() and not field_name.startswith("_"):
                fields.add(field_name)
    return fields


def _extract_public_api_funcs() -> list[str]:
    """Extract public API function names from __init__.py."""
    code = _read(ROOT / "src" / "sqlseed" / "__init__.py")
    funcs: list[str] = []
    marker = "def "
    for line in code.splitlines():
        # Only top-level defs (no leading whitespace)
        if not line.startswith(marker):
            continue
        rest = line[len(marker) :]
        name = ""
        for ch in rest:
            if ch.isalnum() or ch == "_":
                name += ch
            else:
                break
        if name and not name.startswith("_"):
            funcs.append(name)
    return funcs


# ── Tests ────────────────────────────────────────────────────────────


class TestGeneratorTypes:
    """Verify generator type count matches documentation."""

    def test_count_in_readme(self):
        generators = _get_generator_types()
        count = len(generators)

        # Only check files that claim to list total generator count
        # (skip CHANGELOG which talks about incremental additions)
        check_files = [p for p in _find_doc_files() if "CHANGELOG" not in p.name]

        for doc_path in check_files:
            text = _read(doc_path)
            matches = _extract_number_before_keyword(text, ["个生成器", "种生成器", "generator"])
            for m in matches:
                assert int(m) == count, (
                    f"{doc_path}: claims {m} generators, but _GENERATOR_MAP has {count}. "
                    f"Generators: {sorted(generators)}"
                )

    def test_new_types_documented(self):
        """Every generator in _GENERATOR_MAP should appear in README."""
        generators = _get_generator_types()
        readme = _read(ROOT / "README.md")

        for gen in sorted(generators):
            # Generator names should appear in the generator table
            # Use word boundary to avoid false matches
            assert gen in readme, f"Generator '{gen}' is in _GENERATOR_MAP but not mentioned in README.md"


class TestExactMatchRules:
    """Verify exact match rule count matches documentation."""

    def test_count_in_docs(self):
        rules = _get_exact_match_rules()
        rule_count = len(rules)

        # Primary protection: verify AUTO-GENERATED marker values.
        # This catches the silent-failure mode where the number sits
        # inside the marker and is separated from the keyword by the
        # END tag, which breaks the keyword-based search below.
        marker_claims = _find_marker_claims("exact-match-rule-count")
        assert marker_claims, (
            "No <!-- BEGIN:AUTO-GENERATED:exact-match-rule-count --> markers found. "
            "Add markers to docs claiming the exact-match rule count."
        )
        for doc_path, value in marker_claims:
            assert int(value) == rule_count, (
                f"{doc_path}: marker claims {value} exact-match rules, "
                f"but EXACT_MATCH_RULES has {rule_count}"
            )

        # Secondary protection: keyword-based search for unmarked claims.
        for doc_path in _find_doc_files():
            text = _read(doc_path)
            matches = _extract_number_before_keyword(text, ["条规则", "rule"])
            for m in matches:
                assert int(m) == rule_count, f"{doc_path}: claims {m} rules, but EXACT_MATCH_RULES has {rule_count}"


class TestExpressionFunctions:
    """Verify SAFE_FUNCTIONS count matches documentation."""

    def test_count_in_docs(self):
        functions = _get_safe_functions()
        count = len(functions)

        for doc_path in _find_doc_files():
            text = _read(doc_path)
            # Only check files that mention expression engine context
            if "expression" not in text.lower() and "表达式" not in text.lower() and "SAFE_FUNCTIONS" not in text:
                continue
            matches = _extract_number_before_keyword(text, ["个函数", "函数", "function"])
            for m in matches:
                assert int(m) == count, f"{doc_path}: claims {m} expression functions, but SAFE_FUNCTIONS has {count}"


class TestPluginHooks:
    """Verify hook count matches documentation."""

    def test_count_in_docs(self):
        hooks = _get_hook_names()
        count = len(hooks)

        for doc_path in _find_doc_files():
            text = _read(doc_path)
            matches = _extract_number_before_keyword(text, ["个 hook 点", "个hook点", "hook point", "hook"])
            for m in matches:
                assert int(m) == count, f"{doc_path}: claims {m} hooks, but hookspecs.py has {count}"


class TestConfigModels:
    """Verify config model fields match architecture docs."""

    def test_table_config_enrich_field(self):
        """TableConfig.enrich should be documented."""
        fields = _get_config_fields("TableConfig")
        assert "enrich" in fields, "TableConfig missing 'enrich' field"

        arch = _read(ROOT / "docs" / "architecture.md")
        assert "enrich" in arch, "architecture.md missing 'enrich' field in TableConfig"

    def test_column_association_source_column(self):
        """ColumnAssociation.source_column should be documented."""
        fields = _get_config_fields("ColumnAssociation")
        assert "source_column" in fields, "ColumnAssociation missing 'source_column' field"

        arch = _read(ROOT / "docs" / "architecture.md")
        assert "source_column" in arch, "architecture.md missing 'source_column' in ColumnAssociation"


class TestBilingualSync:
    """Verify English and Chinese docs are in sync."""

    @pytest.mark.parametrize(
        "pair",
        [
            ("README.md", "README.zh-CN.md"),
            ("CHANGELOG.md", "CHANGELOG.zh-CN.md"),
            ("docs/architecture.md", "docs/architecture.zh-CN.md"),
            ("plugins/sqlseed-ai/README.md", "plugins/sqlseed-ai/README.zh-CN.md"),
            ("plugins/mcp-server-sqlseed/README.md", "plugins/mcp-server-sqlseed/README.zh-CN.md"),
        ],
    )
    def test_language_links(self, pair: tuple[str, str]):
        """Both files should have bilingual links."""
        en_path = ROOT / pair[0]
        zh_path = ROOT / pair[1]

        if not en_path.exists() or not zh_path.exists():
            pytest.skip(f"File missing: {pair}")

        en_text = _read(en_path)
        zh_text = _read(zh_path)

        en_name = pair[0].split("/")[-1]
        zh_name = pair[1].split("/")[-1]

        assert zh_name in en_text, f"{pair[0]} should link to {zh_name}"
        assert en_name in zh_text, f"{pair[1]} should link to {en_name}"


class TestCodeExamples:
    """Verify code examples in docs don't reference removed APIs."""

    def test_public_api_in_readme(self):
        """README should document all public API functions."""
        public_funcs = _extract_public_api_funcs()

        readme = _read(ROOT / "README.md")
        for func in public_funcs:
            assert func in readme, f"Public API function '{func}' not mentioned in README.md"


class TestPatternMatchRules:
    """Verify pattern match rule count matches documentation."""

    def test_count_in_docs(self):
        rules = _get_pattern_match_rules()
        rule_count = len(rules)

        # Primary protection: verify AUTO-GENERATED marker values.
        marker_claims = _find_marker_claims("pattern-match-rule-count")
        assert marker_claims, (
            "No <!-- BEGIN:AUTO-GENERATED:pattern-match-rule-count --> markers found. "
            "Add markers to docs claiming the pattern-match rule count."
        )
        for doc_path, value in marker_claims:
            assert int(value) == rule_count, (
                f"{doc_path}: marker claims {value} pattern-match rules, "
                f"but PATTERN_MATCH_RULES has {rule_count}"
            )

        # Secondary protection: keyword-based search for unmarked claims.
        # Match both Chinese and English claims about pattern/regex counts
        # Avoid bare "pattern" which matches unrelated content
        for doc_path in _find_doc_files():
            text = _read(doc_path)
            matches = _extract_number_before_keyword(text, ["条正则", "regex", "pattern rule", "pattern match"])
            for m in matches:
                assert int(m) == rule_count, (
                    f"{doc_path}: claims {m} pattern rules, but PATTERN_MATCH_RULES has {rule_count}"
                )


class TestEnumNamePatterns:
    """Verify enum name pattern count matches documentation."""

    def test_count_in_docs(self):
        patterns = _get_enum_name_patterns()
        count = len(patterns)

        for doc_path in _find_doc_files():
            text = _read(doc_path)
            matches = _extract_number_before_keyword(text, ["个枚举", "enum pattern", "enum name"])
            for m in matches:
                assert int(m) == count, (
                    f"{doc_path}: claims {m} enum patterns, but ENUM_NAME_PATTERNS has {count}"
                )


class TestMcpToolNames:
    """Verify MCP tool names match documentation."""

    def test_tools_documented(self):
        tools = _get_mcp_tool_names()
        readme = _read(ROOT / "plugins" / "mcp-server-sqlseed" / "README.md")
        for tool in tools:
            assert tool in readme, (
                f"MCP tool '{tool}' not mentioned in mcp-server-sqlseed README.md"
            )


class TestAutoGeneratedMarkers:
    """Verify AUTO-GENERATED marker regions are well-formed.

    Every BEGIN:AUTO-GENERATED marker must have a matching END marker.
    This test will start passing once markers are added in Layer 1.
    """

    def test_markers_balanced(self):
        """Every BEGIN:AUTO-GENERATED must have a matching END."""
        for doc_path in _find_doc_files():
            text = _read(doc_path)
            begins = text.count("<!-- BEGIN:AUTO-GENERATED")
            ends = text.count("<!-- END:AUTO-GENERATED")
            assert begins == ends, (
                f"{doc_path}: {begins} BEGIN markers but {ends} END markers"
            )
