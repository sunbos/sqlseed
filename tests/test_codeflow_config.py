"""Keep CodeFlow's legacy Pylint configuration aligned with project policy."""

from __future__ import annotations

import configparser
import sys
from pathlib import Path

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


def test_codeflow_config_matches_modern_pylint_policy() -> None:
    """Preserve shared settings and keep fixture shadowing checks enabled."""
    modern_sections = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pylint"]
    modern = {name: value for section in modern_sections.values() for name, value in section.items()}
    codeflow = configparser.ConfigParser(interpolation=None)
    configuration_path = ROOT / ".pylintrc"
    assert codeflow.read(configuration_path, encoding="utf-8") == [str(configuration_path)]
    legacy = {name: value.strip() for section in codeflow.sections() for name, value in codeflow.items(section)}

    # Keep observed remote checkers even if a custom rc file replaces defaults.
    extensions = {name.strip() for name in legacy.pop("load-plugins", "").split(",") if name.strip()}
    assert extensions == CODEFLOW_EXTENSIONS
    assert {option: legacy.pop(option, None) for option in CODEFLOW_DESIGN_LIMITS} == CODEFLOW_DESIGN_LIMITS
    # Additional options must be reviewed rather than silently changing scope.
    assert set(legacy) == set(modern) == {"disable", "max-line-length", "good-names-rgxs"}
    assert legacy["max-line-length"] == str(modern["max-line-length"])
    assert legacy["good-names-rgxs"] == modern["good-names-rgxs"]

    modern_disabled = set(modern["disable"])
    legacy_disabled = {message.strip() for message in legacy["disable"].split(",") if message.strip()}
    assert modern_disabled - legacy_disabled == MODERN_ONLY_MESSAGES
    assert legacy_disabled - modern_disabled == set()
    # Pylint also accepts categories and checker names as disable selectors.
    assert {"all", "w", "warning", "warnings", "variables", "w0621", "redefined-outer-name"}.isdisjoint(
        message.lower() for message in modern_disabled | legacy_disabled
    )
