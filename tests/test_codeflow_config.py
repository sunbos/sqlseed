"""Keep CodeFlow's legacy Pylint configuration aligned with project policy."""

from __future__ import annotations

import ast
import configparser
import sys
from pathlib import Path
from typing import NamedTuple

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
# R0917 was introduced in Pylint 3.3; CodeFlow reports Pylint 2.17.7.
MODERN_ONLY_MESSAGES = {"too-many-positional-arguments"}
# These extensions emitted findings in CodeFlow's analysis of commit 5b0dd07.
CODEFLOW_EXTENSIONS = {
    "pylint.extensions.bad_builtin",
    "pylint.extensions.code_style",
    "pylint.extensions.docparams",
    "pylint.extensions.mccabe",
    "pylint.extensions.overlapping_exceptions",
    "pylint.extensions.redefined_variable_type",
    "pylint.extensions.set_membership",
}
# Limits shown in CodeFlow's 5b0dd07 findings (for example 36/11, 964/100, 358/27).
CODEFLOW_DESIGN_LIMITS = {"max-returns": "11", "max-statements": "100", "max-branches": "27"}


class ManifestImport(NamedTuple):
    """Distribution declaration backing a third-party module exception."""

    distribution: str
    manifest: str


# Import roots are not always distribution names. Each mapping is reviewed and
# checked against its declaring manifest rather than the test runner's packages.
MANIFEST_IMPORTS = {
    "click": ManifestImport("click", "plugins/sqlseed-cli/pyproject.toml"),
    "faker": ManifestImport("faker", "pyproject.toml"),
    "fastapi": ManifestImport("fastapi", "plugins/sqlseed-web/pyproject.toml"),
    "httpx": ManifestImport("httpx", "plugins/sqlseed-ai/pyproject.toml"),
    "hypothesis": ManifestImport("hypothesis", "plugins/sqlseed-ai/pyproject.toml"),
    "mcp": ManifestImport("mcp", "plugins/mcp-server-sqlseed/pyproject.toml"),
    "openai": ManifestImport("openai", "plugins/sqlseed-ai/pyproject.toml"),
    "packaging": ManifestImport("packaging", "plugins/sqlseed-web/pyproject.toml"),
    "pluggy": ManifestImport("pluggy", "pyproject.toml"),
    "pydantic": ManifestImport("pydantic", "pyproject.toml"),
    "pytest": ManifestImport("pytest", "pyproject.toml"),
    "rich": ManifestImport("rich", "plugins/sqlseed-cli/pyproject.toml"),
    "rstr": ManifestImport("rstr", "pyproject.toml"),
    "simpleeval": ManifestImport("simpleeval", "pyproject.toml"),
    "sqlalchemy": ManifestImport("sqlalchemy", "pyproject.toml"),
    "sqlglot": ManifestImport("sqlglot", "pyproject.toml"),
    "structlog": ManifestImport("structlog", "pyproject.toml"),
    "testcontainers": ManifestImport("testcontainers", "pyproject.toml"),
    "tqdm": ManifestImport("tqdm", "pyproject.toml"),
    "typing_extensions": ManifestImport("typing-extensions", "pyproject.toml"),
    "uvicorn": ManifestImport("uvicorn", "plugins/sqlseed-web/pyproject.toml"),
    "yaml": ManifestImport("pyyaml", "pyproject.toml"),
}
# These imports belong to locked transitive dependencies: Docker/testcontainers,
# FastAPI/Starlette, the Python 3.10 TOML fallback, and Windows pywin32 support.
CI_IMPORTS = {
    "docker": "docker",
    "pywintypes": "pywin32",
    "requests": "requests",
    "starlette": "starlette",
    "tomli": "tomli",
    "winerror": "pywin32",
}
# Windows-only modules are listed in sys.stdlib_module_names on every platform.
WINDOWS_STDLIB_IMPORTS = {"msvcrt"}
ENVIRONMENT_OPTIONS = {"source-roots", "init-hook", "ignored-modules"}
SCRIPT_PACKAGES = ("scripts/complex_validation", "examples/scenario_lab")
DIRECT_SCRIPT_PATHS = (*SCRIPT_PACKAGES, "examples")


def _codeflow_options() -> dict[str, str]:
    configuration = configparser.ConfigParser(interpolation=None)
    configuration_path = ROOT / ".pylintrc"
    assert configuration.read(configuration_path, encoding="utf-8") == [str(configuration_path)]
    return {name: value.strip() for section in configuration.sections() for name, value in configuration.items(section)}


def _manifest_packages() -> list[Path]:
    manifests = [ROOT / "pyproject.toml", *sorted((ROOT / "plugins").glob("*/pyproject.toml"))]
    return [
        manifest.parent / package
        for manifest in manifests
        for package in tomllib.loads(manifest.read_text(encoding="utf-8"))["tool"]["hatch"]["build"]["targets"][
            "wheel"
        ]["packages"]
    ]


def _csv_values(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _import_references(path: Path) -> list[tuple[int, str, bool]]:
    references = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.ImportFrom):
            references.append((node.lineno, node.module or "", bool(node.level)))
        elif isinstance(node, ast.Import):
            references.extend((node.lineno, alias.name, False) for alias in node.names)
    return references


def _local_import_collisions(path: Path, ignored_modules: set[str]) -> list[str]:
    collisions = []
    # Directly executed scripts put their own directory on sys.path. Installed
    # packages do not: sqlseed_ai/mcp.py legitimately imports the external mcp.
    is_script = path.is_relative_to(ROOT / "scripts") or path.is_relative_to(ROOT / "examples")
    for line, module, relative in _import_references(path):
        if (root := module.split(".", 1)[0]) not in ignored_modules:
            continue
        local_sibling = (path.parent / f"{root}.py").is_file() or (path.parent / root).is_dir()
        if relative or (is_script and local_sibling):
            collisions.append(f"{path.relative_to(ROOT)}:{line}: {module}")
    return collisions


def test_codeflow_config_matches_modern_pylint_policy() -> None:
    """Preserve shared settings and keep fixture shadowing checks enabled."""
    modern_sections = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pylint"]
    modern = {name: value for section in modern_sections.values() for name, value in section.items()}
    legacy = _codeflow_options()

    # Keep observed remote checkers even if a custom rc file replaces defaults.
    extensions = {name.strip() for name in legacy.pop("load-plugins", "").split(",") if name.strip()}
    assert extensions == CODEFLOW_EXTENSIONS
    assert {option: legacy.pop(option, None) for option in CODEFLOW_DESIGN_LIMITS} == CODEFLOW_DESIGN_LIMITS
    # Environment adaptation has separate provenance and internal-import guards.
    assert all(legacy.pop(option, None) for option in ENVIRONMENT_OPTIONS)
    # Additional options must be reviewed rather than silently changing scope.
    assert set(legacy) == set(modern) == {"disable", "max-line-length", "good-names-rgxs"}
    assert legacy["max-line-length"] == str(modern["max-line-length"])
    assert legacy["good-names-rgxs"] == modern["good-names-rgxs"]

    modern_disabled = set(modern["disable"])
    legacy_disabled = {message.strip() for message in legacy["disable"].split(",") if message.strip()}
    assert modern_disabled - legacy_disabled == MODERN_ONLY_MESSAGES
    assert legacy_disabled - modern_disabled == set()
    # Pylint also accepts categories and checker names as disable selectors.
    assert {
        "all",
        "w",
        "warning",
        "warnings",
        "variables",
        "w0621",
        "redefined-outer-name",
        "e",
        "error",
        "errors",
        "imports",
        "e0401",
        "import-error",
        "e0611",
        "no-name-in-module",
    }.isdisjoint(message.lower() for message in modern_disabled | legacy_disabled)


def test_codeflow_source_paths_match_distributable_packages() -> None:
    """Resolve all local packages and shared tests using only local search paths."""
    configuration = _codeflow_options()
    source_roots = _csv_values(configuration["source-roots"])
    package_roots = {package.parent.relative_to(ROOT).as_posix() for package in _manifest_packages()}
    # Specific roots precede the repository root so package names stay canonical;
    # the final root distinguishes plugin tests from the shared tests namespace.
    assert source_roots[-1] == "."
    assert len(source_roots) == len(package_roots) + 1
    assert set(source_roots[:-1]) == package_roots
    search_paths = [*source_roots, *DIRECT_SCRIPT_PATHS]
    assert all((ROOT / directory).is_dir() for directory in search_paths)
    assert all((ROOT / directory / "__init__.py").is_file() for directory in SCRIPT_PACKAGES)
    # Inspect the hook without executing it: only sys and an explicit path list
    # are allowed, with no project imports, installers or other side effects.
    expected_hook = ast.parse(f"import sys; sys.path[:0] = {search_paths!r}")
    assert ast.dump(ast.parse(configuration["init-hook"])) == ast.dump(expected_hook)


def test_codeflow_external_imports_have_dependency_provenance() -> None:
    """Keep missing-dependency exceptions tied to manifests and the CI lock."""
    ignored_modules = _csv_values(_codeflow_options()["ignored-modules"])
    assert len(ignored_modules) == len(set(ignored_modules))
    assert set(ignored_modules) == MANIFEST_IMPORTS.keys() | CI_IMPORTS.keys() | WINDOWS_STDLIB_IMPORTS
    assert sys.stdlib_module_names >= WINDOWS_STDLIB_IMPORTS
    # Exact top-level identifiers exclude wildcard and dotted internal matches.
    assert all(module.isidentifier() for module in ignored_modules)
    source_roots = [
        ROOT,
        *(package.parent for package in _manifest_packages()),
        *(ROOT / p for p in DIRECT_SCRIPT_PATHS),
    ]
    internal_roots = {
        path.stem if path.suffix == ".py" else path.name
        for source in source_roots
        for path in source.iterdir()
        if path.is_dir() or path.suffix == ".py"
    }
    assert internal_roots.isdisjoint(ignored_modules)

    for module, (distribution, manifest_name) in MANIFEST_IMPORTS.items():
        project = tomllib.loads((ROOT / manifest_name).read_text(encoding="utf-8"))["project"]
        groups = [project.get("dependencies", []), *project.get("optional-dependencies", {}).values()]
        declared = {canonicalize_name(Requirement(value).name) for group in groups for value in group}
        assert canonicalize_name(distribution) in declared, (module, distribution, manifest_name)

    locked = {
        canonicalize_name(line.split("==", 1)[0])
        for line in (ROOT / ".github/requirements-ci.txt").read_text(encoding="utf-8").splitlines()
        if line and not line[0].isspace() and "==" in line
    }
    assert set(CI_IMPORTS.values()) <= locked


def test_codeflow_external_exceptions_cannot_hide_local_imports() -> None:
    """Expose Pylint 2.17's unqualified relative-import ignore matching in CI."""
    ignored_modules = set(_csv_values(_codeflow_options()["ignored-modules"]))
    source_roots = [package.parent for package in _manifest_packages()]
    test_roots = [ROOT / "tests", *(source.parent / "tests" for source in source_roots if source != ROOT / "src")]
    files = {
        path
        for directory in (*source_roots, *test_roots, ROOT / "scripts", ROOT / "examples")
        for path in directory.rglob("*.py")
    } | {ROOT / "conftest.py"}
    collisions = [collision for path in sorted(files) for collision in _local_import_collisions(path, ignored_modules)]
    assert not collisions, "External import exceptions would hide internal imports:\n" + "\n".join(collisions)
