from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sqlseed.core.transform import load_transform

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class TestLoadTransform:
    def test_load_valid_transform(self, tmp_path: Path) -> None:
        script = tmp_path / "transform.py"
        script.write_text(
            "def transform_row(row, ctx):\n    row['name'] = row.get('name', '').upper()\n    return row\n"
        )
        # Explicit Callable annotation so static analyzers (pylint/CodeFlow)
        # treat ``fn`` as invocable. Without this, pylint infers the return
        # value of ``load_transform`` as ``Any`` (because the function uses
        # ``Any`` internally for the dynamically-loaded attribute) and raises
        # E1102 (not-callable) on the ``fn(...)`` invocation below.
        fn: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] = load_transform(str(script))
        result: dict[str, Any] = fn({"name": "alice"}, {})

        assert result["name"] == "ALICE"

    def test_load_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="Transform script not found"):
            load_transform(str(tmp_path / "nonexistent.py"))

    def test_load_missing_function(self, tmp_path: Path) -> None:
        script = tmp_path / "bad_transform.py"
        script.write_text("x = 1\n")
        with pytest.raises(AttributeError, match="transform_row"):
            load_transform(str(script))

    def test_load_invalid_syntax(self, tmp_path: Path) -> None:
        script = tmp_path / "syntax_error.py"
        script.write_text("def broken(\n")
        with pytest.raises((ImportError, SyntaxError)):
            load_transform(str(script))

    def test_load_non_callable_transform(self, tmp_path: Path) -> None:
        script = tmp_path / "non_callable.py"
        script.write_text("transform_row = 123  # Not a function\n")
        with pytest.raises(TypeError, match="must be a callable function"):
            load_transform(str(script))
