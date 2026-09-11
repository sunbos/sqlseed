"""Keep changing interfaces and AI vendors outside the offline core contract."""

from __future__ import annotations

import ast
from importlib import metadata
from importlib.util import resolve_name
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10; pytest supplies this compatibility dependency.
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("package", ["sqlseed-web", "sqlseed-cli", "sqlseed-ai", "mcp-server-sqlseed"])
def test_plugin_dependency_rejects_legacy_core_but_accepts_the_current_development_package(package: str) -> None:
    manifest = tomllib.loads((ROOT / "plugins" / package / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = [Requirement(value) for value in manifest["project"]["dependencies"]]
    core = next(requirement for requirement in requirements if requirement.name == "sqlseed")
    # 0.2.3 lacks the Web stream interfaces, CLI URL keyword, AI suggestion hook
    # and MCP target validators. pip must reject these old Core combinations.
    assert Version("0.2.3") not in core.specifier
    assert Version("0.2.4.dev0") in core.specifier
    assert Version(metadata.version("sqlseed")) in core.specifier


def _imports(source: Path, package_root: Path) -> list[tuple[int, str]]:
    package = ".".join(source.parent.relative_to(package_root.parent).parts)
    imports: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imports.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = resolve_name("." * node.level + module, package)
            imports.append((node.lineno, module))
            imports.extend((node.lineno, f"{module}.{alias.name}") for alias in node.names)
    return imports


def _violations(package_root: Path, forbidden: tuple[str, ...]) -> list[str]:
    return [
        f"{source.relative_to(ROOT)}:{line}: {module}"
        for source in sorted(package_root.rglob("*.py"))
        for line, module in _imports(source, package_root)
        if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden)
    ]


def test_offline_core_does_not_import_interfaces_or_model_sdks() -> None:
    forbidden = (
        "sqlseed_ai",
        "sqlseed_cli",
        "sqlseed_web",
        "mcp_server_sqlseed",
        "openai",
        "anthropic",
        "google.genai",
        "google.generativeai",
        "ollama",
    )
    violations = _violations(ROOT / "src/sqlseed", forbidden)
    assert not violations, "Keep plugin/vendor dependencies outside core:\n" + "\n".join(violations)


@pytest.mark.parametrize("package", ["sqlseed-web/src/sqlseed_web", "mcp-server-sqlseed/src/mcp_server_sqlseed"])
def test_non_cli_interfaces_do_not_import_ai_cli(package: str) -> None:
    violations = _violations(ROOT / "plugins" / package, ("sqlseed_ai.cli",))
    assert not violations, "Use the AI application service, not terminal factories:\n" + "\n".join(violations)


def test_ai_runtime_is_independent_of_terminal_entrypoints() -> None:
    package_root = ROOT / "plugins/sqlseed-ai/src/sqlseed_ai"
    source = package_root / "runtime.py"
    forbidden = ("click", "sqlseed_cli", "sqlseed_ai.cli")
    violations = [
        f"{line}: {module}"
        for line, module in _imports(source, package_root)
        if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden)
    ]
    assert not violations, "AI runtime must use ordinary Python calls/errors:\n" + "\n".join(violations)
