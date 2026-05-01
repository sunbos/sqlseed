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


# ── Source Code Fact Extractors ──────────────────────────────────────


def _get_generator_types() -> set[str]:
    """Extract generator type names from _GENERATOR_MAP."""
    code = _read(ROOT / "src" / "sqlseed" / "generators" / "_dispatch.py")
    return set(re.findall(r'"(\w+)":\s*"_gen_', code))


def _get_exact_match_rules() -> dict[str, str]:
    """Extract exact match rules from mapper."""
    code = _read(ROOT / "src" / "sqlseed" / "core" / "mapper.py")
    # Match the EXACT_MATCH_RULES dict entries
    return dict(re.findall(r'"(\w+)":\s*"(\w+)"', code))


def _get_safe_functions() -> set[str]:
    """Extract function names from ExpressionEngine.SAFE_FUNCTIONS."""
    code = _read(ROOT / "src" / "sqlseed" / "core" / "expression.py")
    section = re.search(r"SAFE_FUNCTIONS[^=]*=\s*\{([^}]*)", code, re.DOTALL)
    if not section:
        return set()
    # Only match string keys (exclude numeric like "0")
    return {m for m in re.findall(r'"([a-z_]\w*)":', section.group(1)) if not m.isdigit()}


def _get_hook_names() -> set[str]:
    """Extract hook function names from hookspecs."""
    code = _read(ROOT / "src" / "sqlseed" / "plugins" / "hookspecs.py")
    return set(re.findall(r"def (sqlseed_\w+)", code))


def _get_config_fields(cls_name: str) -> set[str]:
    """Extract field names from a Pydantic model class."""
    code = _read(ROOT / "src" / "sqlseed" / "config" / "models.py")
    # Find the class body using string operations to avoid regex backtracking
    marker = f"class {cls_name}"
    start = code.find(marker)
    if start == -1:
        return set()
    next_class = code.find("\nclass ", start + len(marker))
    body = code[start:] if next_class == -1 else code[start:next_class]
    return set(re.findall(r"^\s+(\w+):\s*", body, re.MULTILINE))


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
            matches = re.findall(
                r"(\d+)\s*(?:generators?|个生成器|generator types?|种生成器)",
                text,
                re.IGNORECASE,
            )
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
        code = _read(ROOT / "src" / "sqlseed" / "core" / "mapper.py")
        # Count entries in EXACT_MATCH_RULES dict
        rule_section = re.search(r"EXACT_MATCH_RULES[^=]*=\s*\{([^}]*)", code, re.DOTALL)
        if not rule_section:
            pytest.skip("Cannot parse EXACT_MATCH_RULES")
        rule_count = len(re.findall(r'"\w+":', rule_section.group(1)))

        for doc_path in _find_doc_files():
            text = _read(doc_path)
            matches = re.findall(r"(\d+)\s*(?:条规则|rules?)", text, re.IGNORECASE)
            for m in matches:
                assert int(m) == rule_count, f"{doc_path}: claims {m} rules, but EXACT_MATCH_RULES has {rule_count}"


class TestExpressionFunctions:
    """Verify SAFE_FUNCTIONS count matches documentation."""

    def test_count_in_docs(self):
        functions = _get_safe_functions()
        count = len(functions)

        for doc_path in _find_doc_files():
            text = _read(doc_path)
            # Match "21 functions" or "21 个函数" (not "11 total" which refers to hooks)
            matches = re.findall(
                r"(\d+)\s*(?:个\s*)?(?:函数|functions?)",
                text,
                re.IGNORECASE,
            )
            for m in matches:
                # Only assert if file also mentions expression engine context
                if "expression" in text.lower() or "表达式" in text.lower() or "SAFE_FUNCTIONS" in text:
                    assert int(m) == count, (
                        f"{doc_path}: claims {m} expression functions, but SAFE_FUNCTIONS has {count}"
                    )


class TestPluginHooks:
    """Verify hook count matches documentation."""

    def test_count_in_docs(self):
        hooks = _get_hook_names()
        count = len(hooks)

        for doc_path in _find_doc_files():
            text = _read(doc_path)
            # Match "11 hooks" or "11 个 Hook" or "11 hook points"
            matches = re.findall(
                r"(\d+)\s*(?:个\s*)?(?:hook|Hook)\s*(?:点|point|s?\b)",
                text,
                re.IGNORECASE,
            )
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
        init_code = _read(ROOT / "src" / "sqlseed" / "__init__.py")
        public_funcs = re.findall(r"^def (\w+)\(", init_code, re.MULTILINE)

        readme = _read(ROOT / "README.md")
        for func in public_funcs:
            assert func in readme, f"Public API function '{func}' not mentioned in README.md"
