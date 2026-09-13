"""Tests for sqlseed._utils.paths — platform-aware cache directory resolution."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sqlseed._utils.paths import _CACHE_DIR_ENV, get_cache_dir


class TestGetCacheDir:
    """Test get_cache_dir() across platforms and configurations."""

    def test_env_override_takes_priority(self, tmp_path: Path) -> None:
        custom = str(tmp_path / "custom_cache")
        with patch.dict(os.environ, {_CACHE_DIR_ENV: custom}):
            result = get_cache_dir()
        assert result == Path(custom)

    def test_env_override_with_subdir(self, tmp_path: Path) -> None:
        custom = str(tmp_path / "custom_cache")
        with patch.dict(os.environ, {_CACHE_DIR_ENV: custom}):
            result = get_cache_dir("snapshots")
        assert result == Path(custom) / "snapshots"

    def test_darwin_uses_library_caches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_CACHE_DIR_ENV, raising=False)
        with (
            patch("sqlseed._utils.paths.sys") as mock_sys,
            patch("sqlseed._utils.paths.Path") as mock_path_cls,
        ):
            mock_sys.platform = "darwin"
            mock_home = Path("/Users/testuser")
            mock_path_cls.home.return_value = mock_home
            result = get_cache_dir()
            assert "Library" in str(result) or result == mock_home / "Library" / "Caches" / "sqlseed"

    def test_linux_uses_xdg_cache(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        xdg_dir = str(tmp_path / "xdg")
        monkeypatch.delenv(_CACHE_DIR_ENV, raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", xdg_dir)
        with patch("sqlseed._utils.paths.sys") as mock_sys:
            mock_sys.platform = "linux"
            result = get_cache_dir()
            assert result == Path(xdg_dir) / "sqlseed"

    def test_returns_path_type(self) -> None:
        result = get_cache_dir()
        assert isinstance(result, Path)

    def test_subdir_appended_correctly(self) -> None:
        base = get_cache_dir()
        with_sub = get_cache_dir("ai_configs")
        assert with_sub == base / "ai_configs"

    def test_empty_subdir_returns_root(self) -> None:
        base = get_cache_dir()
        empty = get_cache_dir("")
        assert base == empty

    def test_does_not_create_directory(self, tmp_path: Path) -> None:
        """get_cache_dir() should NOT create the directory — callers own that."""
        nonexistent = str(tmp_path / "does_not_exist" / "deeply_nested")
        with patch.dict(os.environ, {_CACHE_DIR_ENV: nonexistent}):
            result = get_cache_dir("sub")
        assert not result.exists()

    @pytest.mark.parametrize("subdir", ["snapshots", "ai_configs", "templates"])
    def test_known_subdirs(self, subdir: str) -> None:
        result = get_cache_dir(subdir)
        assert result.name == subdir
