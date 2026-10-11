"""Check the real release collection and template through the offline CLI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_TAGS = (
    "v0.1.1",
    "v0.1.7",
    "v0.1.8",
    "v0.1.9",
    "v0.1.10",
    "v0.1.11",
    "v0.1.12",
    "v0.1.13",
    "v0.1.14",
    "v0.1.15",
    "v0.1.16",
    "v0.1.17",
    "v0.1.18",
    "v0.1.19",
    "v0.1.20",
    "v0.2.1",
    "v0.2.3",
    "v0.2.4",
    "v0.2.5",
    "v0.2.6",
)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """Copy the actual script and reviewed notes without mutating the working tree."""
    paths = [ROOT / "scripts" / "sync_release_notes.py", *(ROOT / ".github" / "release-notes").glob("*.md")]
    for source in paths:
        target = tmp_path / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    return tmp_path


def check(checkout: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the same offline command as CI with this checkout's computed defaults."""
    return subprocess.run(
        [sys.executable, str(checkout / "scripts" / "sync_release_notes.py"), "--check", *arguments],
        capture_output=True,
        encoding="utf-8",
        check=False,
        timeout=20,
        cwd=checkout,
    )


def test_reviewed_collection_and_placeholder_template_pass(checkout: Path) -> None:
    """Real historical prose and intentionally unfilled template text remain valid."""
    result = check(checkout)
    assert result.returncode == 0, result.stderr
    assert "Validated 20 local release notes; no GitHub access" in result.stdout


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("### 新增\n\n- 描述用户可见的新增能力。\n\n", ""),
        ("### 新增", "### 修复"),
        ("## 中文", "## Chinese"),
        ("- [Source / 源码](https://github.com/sunbos/sqlseed/tree/vVERSION)\n", ""),
        ("/tree/vVERSION", "/tree/vPREVIOUS"),
    ],
    ids=["missing-chinese-subsection", "wrong-subsection-order", "wrong-language", "missing-source", "wrong-source"],
)
def test_default_check_rejects_damaged_template(checkout: Path, old: str, new: str) -> None:
    """Template regressions must fail the real CLI even while all release notes remain valid."""
    template = checkout / ".github" / "release-notes" / "TEMPLATE.md"
    body = template.read_text(encoding="utf-8")
    assert old in body
    template.write_text(body.replace(old, new), encoding="utf-8", newline="\n")
    result = check(checkout)
    assert result.returncode == 1, result.stdout
    assert "TEMPLATE.md" in result.stderr


def test_default_check_requires_every_template_subsection(checkout: Path) -> None:
    """Removing both translations must not silently narrow the release template."""
    template = checkout / ".github" / "release-notes" / "TEMPLATE.md"
    body = template.read_text(encoding="utf-8")
    body = body.replace("### Added\n\n- Describe a user-visible addition.\n\n", "")
    body = body.replace("### 新增\n\n- 描述用户可见的新增能力。\n\n", "")
    template.write_text(body, encoding="utf-8", newline="\n")
    result = check(checkout)
    assert result.returncode == 1, result.stdout
    assert "TEMPLATE.md" in result.stderr


def test_default_check_requires_template_file(checkout: Path) -> None:
    """Deleting the template cannot remove it from the validation set."""
    (checkout / ".github" / "release-notes" / "TEMPLATE.md").unlink()
    result = check(checkout)
    assert result.returncode == 1, result.stdout
    assert "TEMPLATE.md" in result.stderr


@pytest.mark.parametrize("tag", HISTORICAL_TAGS)
@pytest.mark.parametrize("mutation", ["delete", "rename"])
def test_default_check_preserves_every_historical_note(checkout: Path, tag: str, mutation: str) -> None:
    """Every original published release must remain present under its exact filename."""
    note = checkout / ".github" / "release-notes" / f"{tag}.md"
    if mutation == "delete":
        note.unlink()
    else:
        note.rename(note.with_name(f"archived-{tag}.md"))
    result = check(checkout)
    assert result.returncode == 1, result.stdout
    assert "Missing required historical release notes" in result.stderr
    assert tag in result.stderr


def test_default_check_accepts_new_release_notes(checkout: Path) -> None:
    """The required historical set is a minimum, so new approved versions can be added."""
    directory = checkout / ".github" / "release-notes"
    body = (directory / "v0.2.6.md").read_text(encoding="utf-8").replace("v0.2.6", "v0.2.7")
    (directory / "v0.2.7.md").write_text(body, encoding="utf-8", newline="\n")
    result = check(checkout)
    assert result.returncode == 0, result.stderr
    assert "Validated 21 local release notes" in result.stdout


def test_explicit_tag_keeps_subset_contract(checkout: Path) -> None:
    """A selected release can be checked without requiring other notes or a template."""
    directory = checkout / ".github" / "release-notes"
    for path in directory.glob("*.md"):
        if path.name != "v0.2.6.md":
            path.unlink()
    result = check(checkout, "--tag", "v0.2.6")
    assert result.returncode == 0, result.stderr
    assert "Validated 1 local release notes" in result.stdout


@pytest.mark.parametrize("repo", ["sunbos/sqlseed", "owner/fork"])
def test_custom_directory_keeps_subset_contract(checkout: Path, repo: str) -> None:
    """User-provided collections do not inherit sqlseed's historical inventory."""
    directory = checkout / "custom-notes"
    directory.mkdir()
    body = (checkout / ".github" / "release-notes" / "v0.2.6.md").read_text(encoding="utf-8")
    (directory / "v0.2.6.md").write_text(body.replace("sunbos/sqlseed", repo), encoding="utf-8", newline="\n")
    result = check(checkout, "--notes-dir", str(directory), "--repo", repo)
    assert result.returncode == 0, result.stderr
    assert "Validated 1 local release notes" in result.stdout


def test_other_repository_does_not_require_sqlseed_history(checkout: Path) -> None:
    """The default directory remains reusable for a fork's own release collection."""
    directory = checkout / ".github" / "release-notes"
    for path in directory.glob("*.md"):
        if path.name not in {"v0.2.6.md", "TEMPLATE.md"}:
            path.unlink()
        else:
            body = path.read_text(encoding="utf-8").replace("sunbos/sqlseed", "owner/fork")
            path.write_text(body, encoding="utf-8", newline="\n")
    result = check(checkout, "--repo", "owner/fork")
    assert result.returncode == 0, result.stderr
    assert "Validated 1 local release notes" in result.stdout


def test_custom_template_is_checked_when_present(checkout: Path) -> None:
    """A supplied template is checked while a custom collection can omit one."""
    directory = checkout / ".github" / "release-notes"
    custom = checkout / "custom-notes"
    directory.rename(custom)
    (custom / "TEMPLATE.md").write_text("Invalid template.\n", encoding="utf-8", newline="\n")
    result = check(checkout, "--notes-dir", str(custom))
    assert result.returncode == 1, result.stdout
    assert "TEMPLATE.md" in result.stderr
