"""Exercise bilingual output with actual legacy-encoded text streams."""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

import pytest

from tests.test_sync_release_notes import SCRIPT, GitHubProcess, release, sync

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("apply", [False, True], ids=["preview", "apply"])
def test_legacy_stdout_preserves_bilingual_diff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, apply: bool) -> None:
    """Legacy shell encoding cannot prevent previews, backups, or exact updates."""
    body = (SCRIPT.parents[1] / ".github/release-notes/v0.2.6.md").read_text(encoding="utf-8")
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "v0.2.6.md").write_text(body, encoding="utf-8", newline="\n")
    process = GitHubProcess([release(26, "v0.2.6")])
    backup_root = tmp_path / ".release-backups"
    monkeypatch.setattr(sync, "BACKUP_ROOT", backup_root)
    monkeypatch.setattr(sync.subprocess, "run", process.run)
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="ascii")
    monkeypatch.setattr(sync.sys, "stdout", stream)
    arguments = ["--notes-dir", str(notes)]
    if apply:
        arguments.extend(["--apply", "--backup-name", "legacy-output"])
    assert sync.main(arguments) == 0
    stream.flush()
    assert "+## 中文" in buffer.getvalue().decode("utf-8")
    if apply:
        assert process.releases[0]["body"] == body
        backup = backup_root / "legacy-output/v0.2.6.json"
        assert json.loads(backup.read_text(encoding="utf-8")) == process.initial[0]
    else:
        assert process.releases == process.initial
        assert not backup_root.exists()


def test_legacy_stderr_preserves_unicode_error_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Report a failed Unicode notes path without a secondary encoding error."""
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="ascii")
    monkeypatch.setattr(sync.sys, "stderr", stream)
    assert sync.main(["--check", "--notes-dir", str(tmp_path / "说明"), "--tag", "v0.2.6"]) == 1
    stream.flush()
    assert "说明" in buffer.getvalue().decode("utf-8")
