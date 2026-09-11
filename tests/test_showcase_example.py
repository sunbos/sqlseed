"""The showcase example creates isolated databases in private directories."""

from __future__ import annotations

import os
import runpy
import sqlite3
import stat
import tempfile
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def showcase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Keep real temporary allocations within the test-owned directory."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return runpy.run_path(str(Path(__file__).resolve().parents[1] / "examples" / "build_showcase_db.py"))


def test_showcase_databases_have_private_independent_paths(showcase: dict[str, Any]) -> None:
    """Repeated runs preserve their databases without overwriting each other."""
    first = showcase["create_database_path"]()
    second = showcase["create_database_path"]()
    assert first.parent != second.parent
    for path in (first, second):
        assert path.parent.is_dir()
        if os.name != "nt":
            assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        showcase["build_schema"](path)
        with sqlite3.connect(path) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert {"organizations", "departments", "categories"} <= tables
    assert first.is_file() and second.is_file()


def test_showcase_ignores_preexisting_public_symlink(showcase: dict[str, Any], tmp_path: Path) -> None:
    """An attacker-controlled name in the shared temp root is never opened."""
    target = tmp_path / "unintended-target.db"
    public_name = tmp_path / "sqlseed_showcase.db"
    try:
        public_name.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"The platform cannot create a test symlink: {exc}")
    path = showcase["create_database_path"]()
    showcase["build_schema"](path)
    assert path.is_file()
    assert path.parent != tmp_path
    assert public_name.is_symlink()
    assert not target.exists()
