"""Keep every Web regression away from real user preferences."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_web_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQLSEED_WEB_SETTINGS_PATH", str(tmp_path / "web-settings.json"))
