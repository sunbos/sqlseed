"""Exercise release synchronization across the external gh process boundary."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_release_notes.py"
SPEC = importlib.util.spec_from_file_location("sync_release_notes", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise ImportError(f"Cannot load {SCRIPT}")
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)

BODY = """## English

### Fixed

- Preserve release assets.

## 中文

### 修复

- 保留发行资产。

## Links / 相关链接

- [Source](https://github.com/sunbos/sqlseed)
"""


def release(identifier: int, tag: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "node_id": f"release-{identifier}",
        "tag_name": tag,
        "name": "Old title",
        "body": "Historical notes\n",
        "target_commitish": "abcdef0123456789",
        "draft": False,
        "prerelease": False,
        "immutable": False,
        "created_at": "2026-01-01T00:00:00Z",
        "published_at": "2026-01-02T00:00:00Z",
        "updated_at": "2026-01-03T00:00:00Z",
        "assets": [{"id": identifier * 10, "name": "example.whl", "download_count": 12}],
        "author": {"login": "maintainer"},
    }


class GitHubProcess:
    def __init__(self, releases: list[dict[str, Any]]) -> None:
        self.releases = deepcopy(releases)
        self.initial = deepcopy(releases)
        self.commands: list[list[str]] = []
        self.backup_dir: Path | None = None
        self.fail_patch: int | None = None
        self.conflict: dict[str, Any] = {}
        self.mutate_after_patch: dict[str, Any] = {}

    def run(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        endpoint = command[4]
        if endpoint.endswith("/releases?per_page=100"):
            assert "--paginate" in command and "--slurp" in command
            return subprocess.CompletedProcess(command, 0, json.dumps([[item] for item in self.releases]), "")
        identifier = int(endpoint.rsplit("/", 1)[1])
        current = next(item for item in self.releases if item["id"] == identifier)
        if command[3] == "PATCH":
            assert command[-2:] == ["--input", "-"]
            if self.backup_dir is not None:
                for original in self.initial:
                    backup = self.backup_dir / f"{original['tag_name']}.json"
                    assert json.loads(backup.read_text(encoding="utf-8")) == original
            if identifier == self.fail_patch:
                return subprocess.CompletedProcess(command, 1, "", "HTTP 401 Bearer ghp_secret_do_not_print")
            payload = json.loads(kwargs["input"])
            assert set(payload) == {"name", "body"}
            current.update(payload)
            current["updated_at"] = "2026-10-12T00:00:00Z"
            current.update(self.mutate_after_patch)
        else:
            current.update(self.conflict)
        return subprocess.CompletedProcess(command, 0, json.dumps(current), "")


@pytest.fixture
def notes_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "notes"
    directory.mkdir()
    for tag in ("v0.2.5", "v0.2.6"):
        (directory / f"{tag}.md").write_text(BODY, encoding="utf-8", newline="\n")
    return directory


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> GitHubProcess:
    process = GitHubProcess([release(25, "v0.2.5"), release(26, "v0.2.6")])
    monkeypatch.setattr(sync.subprocess, "run", process.run)
    return process


def test_default_preview_reads_all_pages_without_writes(
    notes_dir: Path, github: GitHubProcess, capsys: pytest.CaptureFixture[str]
) -> None:
    assert sync.main(["--notes-dir", str(notes_dir)]) == 0
    assert github.releases == github.initial
    assert [command[3] for command in github.commands] == ["GET"]
    output = capsys.readouterr().out
    assert "v0.2.5: would update" in output
    assert "v0.2.6: would update" in output
    assert "+### 修复" in output
    assert "Preview only" in output


def test_offline_check_does_not_invoke_gh(notes_dir: Path, github: GitHubProcess) -> None:
    assert sync.main(["--check", "--notes-dir", str(notes_dir)]) == 0
    assert github.commands == []


@pytest.mark.parametrize(
    "arguments",
    [
        ["--tag", "v0.2.7"],
        ["--tag", "../../escape"],
        ["--tag", "0.2.6"],
        ["--tag", "v0.2.6", "--tag", "v0.2.6"],
    ],
)
def test_bad_selectors_fail_before_github(notes_dir: Path, github: GitHubProcess, arguments: list[str]) -> None:
    assert sync.main(["--notes-dir", str(notes_dir), *arguments]) == 1
    assert github.commands == []


@pytest.mark.parametrize(
    "body",
    [
        BODY.rstrip("\n").encode(),
        BODY.replace("\n", "\r\n").encode(),
        b"\xff",
        ("\ufeff" + BODY).encode(),
        BODY.replace("## 中文", "## Chinese").encode(),
        BODY.replace("### 修复", "### 新增").encode(),
        BODY.replace("### Fixed", "### Other").encode(),
        BODY.replace("### Fixed", "### Fixed\n\n### Fixed").encode(),
        BODY.replace("### Fixed", "### Fixed\n\n### Added").replace("### 修复", "### 修复\n\n### 新增").encode(),
        BODY.replace("### Fixed\n", "").replace("### 修复\n", "").encode(),
        BODY.replace("### Fixed", "# Extra title\n\n### Fixed").encode(),
        BODY.replace("### Fixed", "### Fixed\n\n#### Extra heading").encode(),
        BODY.replace("Source", "vVERSION").encode(),
        BODY.replace("Source", "vPREVIOUS").encode(),
    ],
)
def test_malformed_notes_stop_before_network(notes_dir: Path, github: GitHubProcess, body: bytes) -> None:
    (notes_dir / "v0.2.6.md").write_bytes(body)
    assert sync.main(["--notes-dir", str(notes_dir)]) == 1
    assert github.commands == []


def test_code_fence_headings_are_content(notes_dir: Path, github: GitHubProcess) -> None:
    body = BODY.replace(
        "- Preserve release assets.",
        "- Preserve release assets.\n\n```markdown\n## Heading in example\n#### Other heading\n```",
    )
    (notes_dir / "v0.2.6.md").write_text(body, encoding="utf-8", newline="\n")
    assert sync.main(["--check", "--notes-dir", str(notes_dir)]) == 0
    assert github.commands == []


@pytest.mark.parametrize("condition", ["missing", "duplicate", "draft"])
def test_every_selected_version_must_have_one_published_release(
    notes_dir: Path, github: GitHubProcess, tmp_path: Path, condition: str
) -> None:
    if condition == "missing":
        github.releases.pop()
    elif condition == "duplicate":
        github.releases.append(deepcopy(github.releases[-1]))
    else:
        github.releases[-1]["draft"] = True
    backups = tmp_path / "backups"
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-dir", str(backups)]) == 1
    assert not backups.exists()
    assert all(command[3] == "GET" for command in github.commands)


def test_apply_requires_external_backup_directory(notes_dir: Path, github: GitHubProcess) -> None:
    for arguments in (["--apply"], ["--apply", "--backup-dir", str(notes_dir / "backups")]):
        with pytest.raises(SystemExit) as error:
            sync.main(["--notes-dir", str(notes_dir), *arguments])
        assert error.value.code == 2
    assert github.commands == []


def test_apply_changes_only_titles_and_bodies_and_saves_full_originals(
    notes_dir: Path, github: GitHubProcess, tmp_path: Path
) -> None:
    github.backup_dir = tmp_path / "backups"
    github.releases[-1]["prerelease"] = True
    github.initial = deepcopy(github.releases)
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-dir", str(github.backup_dir)]) == 0
    for original, updated in zip(github.initial, github.releases, strict=True):
        assert updated == {
            **original,
            "name": original["tag_name"],
            "body": BODY,
            "updated_at": "2026-10-12T00:00:00Z",
        }
        assert json.loads((github.backup_dir / f"{original['tag_name']}.json").read_text(encoding="utf-8")) == original


def test_specific_tag_leaves_other_releases_alone(notes_dir: Path, github: GitHubProcess, tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    assert sync.main(["--notes-dir", str(notes_dir), "--tag", "v0.2.6", "--apply", "--backup-dir", str(backups)]) == 0
    assert github.releases[0] == github.initial[0]
    assert github.releases[1]["name"] == "v0.2.6"
    assert sorted(path.name for path in backups.iterdir()) == ["v0.2.6.json"]


@pytest.mark.parametrize("field,value", [("body", "Edited by someone else"), ("updated_at", "2026-10-11T00:00:00Z")])
def test_concurrent_changes_stop_before_patch(
    notes_dir: Path, github: GitHubProcess, tmp_path: Path, field: str, value: str
) -> None:
    backups = tmp_path / "backups"
    github.conflict = {field: value}
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-dir", str(backups)]) == 1
    assert all(command[3] == "GET" for command in github.commands)
    assert len(list(backups.glob("*.json"))) == 2
    assert github.releases[0][field] == value


def test_partial_failure_retains_all_backups_and_never_prints_credentials(
    notes_dir: Path, github: GitHubProcess, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    github.backup_dir = tmp_path / "backups"
    github.fail_patch = 26
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-dir", str(github.backup_dir)]) == 1
    assert github.releases[0]["body"] == BODY
    assert github.releases[1] == github.initial[1]
    assert len(list(github.backup_dir.glob("*.json"))) == 2
    output = capsys.readouterr()
    assert "ghp_secret" not in output.out + output.err
    assert "earlier updates" in output.err
    assert "auth status" in output.err


def test_existing_backup_is_never_overwritten(notes_dir: Path, github: GitHubProcess, tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    backups.mkdir()
    previous = backups / "v0.2.6.json"
    previous.write_text("previous original", encoding="utf-8")
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-dir", str(backups)]) == 1
    assert previous.read_text(encoding="utf-8") == "previous original"
    assert github.releases == github.initial


def test_verification_detects_changed_assets_and_stops_remaining_updates(
    notes_dir: Path, github: GitHubProcess, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    github.mutate_after_patch = {"assets": []}
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-dir", str(tmp_path / "backups")]) == 1
    assert github.releases[1] == github.initial[1]
    assert "verification failed" in capsys.readouterr().err


def test_second_apply_is_idempotent(notes_dir: Path, github: GitHubProcess, tmp_path: Path) -> None:
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-dir", str(tmp_path / "first")]) == 0
    github.commands.clear()
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-dir", str(tmp_path / "second")]) == 0
    assert all(command[3] == "GET" for command in github.commands)
