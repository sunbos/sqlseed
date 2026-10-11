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

- [Source](https://github.com/sunbos/sqlseed/tree/v0.2.6)
"""
TEMPLATE = (SCRIPT.parents[1] / ".github" / "release-notes" / "TEMPLATE.md").read_text(encoding="utf-8")
TEMPLATE_INSTRUCTIONS = [
    line for line in TEMPLATE.split("## Links / 相关链接", 1)[0].splitlines() if line.startswith("- ")
]


def release(identifier: int, tag: str) -> dict[str, Any]:
    """Build a complete release with publication metadata and a downloadable asset."""
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


class VirtualClock:
    """Advance elapsed time deterministically without delaying the test process."""

    def __init__(self) -> None:
        self.elapsed = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        """Return elapsed simulated time."""
        return self.elapsed

    def sleep(self, duration: float) -> None:
        """Record a requested wait and advance simulated time."""
        self.sleeps.append(duration)
        self.elapsed += duration


class GitHubProcess:
    """Model GitHub pagination, tag-detachment behavior, conflicts, and failed updates."""

    def __init__(self, releases: list[dict[str, Any]]) -> None:
        self.releases = deepcopy(releases)
        self.initial = deepcopy(releases)
        self.commands: list[list[str]] = []
        self.backup_dir: Path | None = None
        self.fail_patch: int | None = None
        self.conflict: dict[str, Any] = {}
        self.mutate_after_patch: dict[str, Any] = {}
        self.clock = VirtualClock()
        self.read_duration = 0.0
        self.patch_duration = 0.0
        self.patch_starts: list[float] = []
        self.patch_finishes: list[float] = []

    def run(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """Execute a simulated gh request against persistent release state."""
        self.commands.append(command)
        endpoint = command[4]
        if command[3] == "GET":
            self.clock.elapsed += self.read_duration
        if endpoint.endswith("/releases?per_page=100"):
            assert "--paginate" in command
            assert "--slurp" in command
            return subprocess.CompletedProcess(command, 0, json.dumps([[item] for item in self.releases]), "")
        identifier = int(endpoint.rsplit("/", 1)[1])
        current = next(item for item in self.releases if item["id"] == identifier)
        if command[3] == "PATCH":
            self.patch_starts.append(self.clock.monotonic())
            assert command[-2:] == ["--input", "-"]
            if self.backup_dir is not None:
                for original in self.initial:
                    backup = self.backup_dir / f"{original['tag_name']}.json"
                    assert json.loads(backup.read_text(encoding="utf-8")) == original
            if identifier == self.fail_patch:
                return subprocess.CompletedProcess(command, 1, "", "HTTP 401 Bearer ghp_secret_do_not_print")
            payload = json.loads(kwargs["input"])
            assert set(payload) <= {"name", "body", "tag_name"}
            # Match the API behavior guarded against by `gh release edit`.
            current["tag_name"] = payload.get("tag_name", "")
            current.update(payload)
            current["updated_at"] = "2026-10-12T00:00:00Z"
            current.update(self.mutate_after_patch)
            self.clock.elapsed += self.patch_duration
            self.patch_finishes.append(self.clock.monotonic())
        else:
            current.update(self.conflict)
        return subprocess.CompletedProcess(command, 0, json.dumps(current), "")


@pytest.fixture
def notes_dir(tmp_path: Path) -> Path:
    """Create two complete bilingual notes files for end-to-end CLI validation."""
    directory = tmp_path / "notes"
    directory.mkdir()
    for tag in ("v0.2.5", "v0.2.6"):
        (directory / f"{tag}.md").write_text(BODY.replace("v0.2.6", tag), encoding="utf-8", newline="\n")
    return directory


@pytest.fixture(autouse=True)
def isolated_backup_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the fixed repository backup root inside each test's isolated filesystem."""
    monkeypatch.setattr(sync, "BACKUP_ROOT", tmp_path.resolve() / ".release-backups")


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> GitHubProcess:
    """Intercept only the external process boundary, retaining actual script behavior."""
    process = GitHubProcess([release(25, "v0.2.5"), release(26, "v0.2.6")])
    monkeypatch.setattr(sync.subprocess, "run", process.run)
    monkeypatch.setattr(sync, "time", process.clock)
    return process


def test_default_preview_reads_all_pages_without_writes(
    notes_dir: Path, github: GitHubProcess, capsys: pytest.CaptureFixture[str]
) -> None:
    """Default invocation previews both pages while preserving every remote field."""
    assert sync.main(["--notes-dir", str(notes_dir)]) == 0
    assert github.releases == github.initial
    assert [command[3] for command in github.commands] == ["GET"]
    assert github.clock.sleeps == []
    output = capsys.readouterr().out
    assert "v0.2.5: would update" in output
    assert "v0.2.6: would update" in output
    assert "+### 修复" in output
    assert "Preview only" in output


def test_offline_check_does_not_invoke_gh(notes_dir: Path, github: GitHubProcess) -> None:
    """Local validation succeeds without starting a GitHub CLI process."""
    assert sync.main(["--check", "--notes-dir", str(notes_dir)]) == 0
    assert github.commands == []
    assert github.clock.sleeps == []


@pytest.mark.parametrize("arguments", [[], ["--check"], ["--apply", "--backup-name", "placeholders"]])
@pytest.mark.parametrize(
    "body",
    [
        TEMPLATE.replace("vPREVIOUS", "v0.2.5").replace("vVERSION", "v0.2.6"),
        *[
            BODY.replace("- Preserve release assets." if instruction.isascii() else "- 保留发行资产。", instruction)
            for instruction in TEMPLATE_INSTRUCTIONS
        ],
    ],
    ids=["whole-template", *[f"instruction-{index}" for index in range(len(TEMPLATE_INSTRUCTIONS))]],
)
def test_template_instructions_stop_before_network(
    notes_dir: Path,
    github: GitHubProcess,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    body: str,
) -> None:
    """Reject real template prose even when only one language retains a single instruction."""
    (notes_dir / "v0.2.6.md").write_text(body, encoding="utf-8", newline="\n")
    assert not (notes_dir / "TEMPLATE.md").exists()
    assert sync.main([*arguments, "--notes-dir", str(notes_dir)]) == 1
    assert "template instructions" in capsys.readouterr().err
    assert github.commands == []
    assert not sync.BACKUP_ROOT.exists()


@pytest.mark.parametrize(
    "example",
    [
        '- Fixed copied text "Describe a user-visible addition." in published notes.',
        "- Documented `Describe a user-visible addition.` as a template example.",
        "> - Describe a user-visible addition.",
        "```markdown\n- Describe a user-visible addition.\n```",
        "~~~~markdown\n- 描述用户可见的新增能力。\n~~~~",
        "```markdown\n" + TEMPLATE.replace("vPREVIOUS", "v0.2.5").replace("vVERSION", "v0.2.6") + "```",
        "    - Describe a user-visible addition.",
        "\t- 描述用户可见的新增能力。",
    ],
    ids=["quotation", "inline-code", "blockquote", "backtick-fence", "tilde-fence", "full-template", "spaces", "tab"],
)
def test_template_instruction_examples_are_valid(notes_dir: Path, github: GitHubProcess, example: str) -> None:
    """Quoted explanations and code examples are content rather than unfinished template prose."""
    body = BODY.replace("- Preserve release assets.", example)
    (notes_dir / "v0.2.6.md").write_text(body, encoding="utf-8", newline="\n")
    assert sync.main(["--check", "--notes-dir", str(notes_dir)]) == 0
    assert github.commands == []


@pytest.mark.parametrize("instruction", [TEMPLATE_INSTRUCTIONS[0], TEMPLATE_INSTRUCTIONS[-1]])
@pytest.mark.parametrize("prefix", ["", "   ", "- ", "   -   "])
def test_fenced_example_does_not_hide_remaining_template_instruction(
    notes_dir: Path, github: GitHubProcess, capsys: pytest.CaptureFixture[str], instruction: str, prefix: str
) -> None:
    """Standalone instructions outside code still fail, including surrounding whitespace."""
    example = f"```markdown\n{instruction}\n```\n\n{prefix}{instruction.removeprefix('- ')}  "
    body = BODY.replace("- Preserve release assets.", example)
    (notes_dir / "v0.2.6.md").write_text(body, encoding="utf-8", newline="\n")
    assert sync.main(["--check", "--notes-dir", str(notes_dir)]) == 1
    assert "template instructions" in capsys.readouterr().err
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
    """Unknown, malformed, and repeated tags cannot trigger remote requests."""
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
    """Encoding and structural errors are rejected before contacting GitHub."""
    (notes_dir / "v0.2.6.md").write_bytes(body)
    assert sync.main(["--notes-dir", str(notes_dir)]) == 1
    assert github.commands == []


@pytest.mark.parametrize(
    "destination",
    [
        "tree/v0.2.5",
        "blob/v0.2.5/CHANGELOG.md",
        "blob/v0.2.5/CHANGELOG.zh-CN.md",
        "blob/v0.2.5/docs/migration.md",
        "compare/v0.2.4...v0.2.5",
    ],
)
def test_stale_versioned_links_fail_before_network(
    notes_dir: Path, github: GitHubProcess, capsys: pytest.CaptureFixture[str], destination: str
) -> None:
    """Copying old source, changelog, migration, or comparison links cannot pass validation."""
    body = BODY.replace(
        "https://github.com/sunbos/sqlseed/tree/v0.2.6", f"https://github.com/sunbos/sqlseed/{destination}"
    )
    (notes_dir / "v0.2.6.md").write_text(body, encoding="utf-8", newline="\n")
    assert sync.main(["--notes-dir", str(notes_dir)]) == 1
    assert "release link target 'v0.2.5' must match v0.2.6" in capsys.readouterr().err
    assert github.commands == []


def test_current_links_allow_previous_comparison_base_and_historical_body_references(
    notes_dir: Path, github: GitHubProcess
) -> None:
    """Only final release links target the current tag; earlier compatibility references stay valid."""
    body = BODY.replace(
        "- Preserve release assets.",
        "- Compare [older behavior](https://github.com/sunbos/sqlseed/blob/v0.2.4/docs/migration.md).",
    ).replace(
        "- [Source](https://github.com/sunbos/sqlseed/tree/v0.2.6)",
        "- [Source](https://github.com/sunbos/sqlseed/tree/v0.2.6)\n"
        "- [Changelog](https://github.com/sunbos/sqlseed/blob/v0.2.6/CHANGELOG.md#fixed)\n"
        "- [Full diff](https://github.com/sunbos/sqlseed/compare/v0.2.5...v0.2.6)\n"
        "- [Original comparison](https://github.com/sunbos/sqlseed/compare/v0.2.3...v0.2.6)\n"
        "- [Dependency](https://github.com/example/dependency/tree/v1.0.0)",
    )
    (notes_dir / "v0.2.6.md").write_text(body, encoding="utf-8", newline="\n")
    assert sync.main(["--check", "--notes-dir", str(notes_dir)]) == 0
    assert github.commands == []


def test_versioned_links_follow_explicit_repository_selection(notes_dir: Path, github: GitHubProcess) -> None:
    """A custom repository receives the same stale-link validation as the default repository."""
    body = BODY.replace("https://github.com/sunbos/sqlseed/tree/v0.2.6", "https://github.com/owner/fork/tree/v0.2.5")
    (notes_dir / "v0.2.6.md").write_text(body, encoding="utf-8", newline="\n")
    assert sync.main(["--check", "--notes-dir", str(notes_dir), "--repo", "owner/fork"]) == 1
    assert github.commands == []


def test_code_fence_headings_are_content(notes_dir: Path, github: GitHubProcess) -> None:
    """Markdown examples must not become release-note section headings."""
    body = BODY.replace(
        "- Preserve release assets.",
        "- Preserve release assets.\n\n```markdown\n## Heading in example\n#### Other heading\n```",
    )
    (notes_dir / "v0.2.6.md").write_text(body, encoding="utf-8", newline="\n")
    assert sync.main(["--check", "--notes-dir", str(notes_dir)]) == 0
    assert github.commands == []


@pytest.mark.parametrize("empty_content", ["", " \n\t", "```python\n \n```", "~~~text\n~~~"])
@pytest.mark.parametrize("empty_heading", ["### Added", "### 新增"])
def test_empty_subsection_is_rejected_even_with_other_nonempty_subsections(
    notes_dir: Path,
    github: GitHubProcess,
    capsys: pytest.CaptureFixture[str],
    empty_content: str,
    empty_heading: str,
) -> None:
    """Content in a sibling subsection cannot compensate for an empty declared subsection."""
    body = BODY.replace("### Fixed", "### Added\n\nAdded content.\n\n### Fixed").replace(
        "### 修复", "### 新增\n\nAdded content.\n\n### 修复"
    )
    body = body.replace(f"{empty_heading}\n\nAdded content.", f"{empty_heading}\n\n{empty_content}")
    (notes_dir / "v0.2.6.md").write_text(body, encoding="utf-8", newline="\n")
    assert sync.main(["--notes-dir", str(notes_dir)]) == 1
    assert github.commands == []
    assert f"{empty_heading} must contain nonwhitespace content" in capsys.readouterr().err


def test_fenced_code_alone_is_valid_subsection_content(notes_dir: Path, github: GitHubProcess) -> None:
    """Actual code counts as content even when the subsection has no surrounding prose."""
    body = BODY.replace("- Preserve release assets.", "```markdown\n### Example code\n```")
    (notes_dir / "v0.2.6.md").write_text(body, encoding="utf-8", newline="\n")
    assert sync.main(["--check", "--notes-dir", str(notes_dir)]) == 0
    assert github.commands == []


def test_long_fences_preserve_content_and_ignore_shorter_delimiters(notes_dir: Path, github: GitHubProcess) -> None:
    """Long delimiter runs use the same fence semantics as ordinary Markdown."""
    fence = "~" * 100_000
    example = f"   {fence}markdown\n~~~\n## Code heading\n   {fence}\n"
    body = BODY.replace("- Preserve release assets.", example)
    (notes_dir / "v0.2.6.md").write_text(body, encoding="utf-8", newline="\n")
    assert sync.main(["--check", "--notes-dir", str(notes_dir)]) == 0
    assert github.commands == []


def test_unclosed_fence_fails_before_network(notes_dir: Path, github: GitHubProcess) -> None:
    """A shorter closing marker must not hide structural headings."""
    body = BODY.replace("- Preserve release assets.", "````markdown\nExample\n```")
    (notes_dir / "v0.2.6.md").write_text(body, encoding="utf-8", newline="\n")
    assert sync.main(["--notes-dir", str(notes_dir)]) == 1
    assert github.commands == []


@pytest.mark.parametrize("condition", ["missing", "duplicate", "draft"])
def test_every_selected_version_must_have_one_published_release(
    notes_dir: Path, github: GitHubProcess, tmp_path: Path, condition: str
) -> None:
    """Missing, duplicate, or draft releases stop the whole selection before backups or writes."""
    if condition == "missing":
        github.releases.pop()
    elif condition == "duplicate":
        github.releases.append(deepcopy(github.releases[-1]))
    else:
        github.releases[-1]["draft"] = True
    backups = sync.BACKUP_ROOT / "backups"
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-name", backups.name]) == 1
    assert not backups.exists()
    assert all(command[3] == "GET" for command in github.commands)


def test_missing_required_release_field_is_not_masked_by_extra_fields(
    notes_dir: Path, github: GitHubProcess, capsys: pytest.CaptureFixture[str]
) -> None:
    """An incomparable key set still lacks a required field and must be rejected."""
    github.releases[0].pop("body")
    github.releases[0]["additional_api_field"] = "extra data"
    assert sync.main(["--notes-dir", str(notes_dir)]) == 1
    assert "incomplete release record" in capsys.readouterr().err
    assert all(command[3] == "GET" for command in github.commands)


def test_apply_requires_explicit_backup_name(notes_dir: Path, github: GitHubProcess) -> None:
    """The CLI requires an explicit backup name before any remote access."""
    with pytest.raises(SystemExit) as error:
        sync.main(["--notes-dir", str(notes_dir), "--apply"])
    assert error.value.code == 2
    assert github.commands == []


@pytest.mark.parametrize("name", ["", ".", "..", "../outside", "/outside", r"C:\outside", "a/b", r"a\b", "a b", "中文"])
def test_unsafe_backup_names_fail_before_network(notes_dir: Path, github: GitHubProcess, name: str) -> None:
    """Backup names cannot supply paths, traversal components, whitespace, or non-ASCII text."""
    with pytest.raises(SystemExit) as error:
        sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-name", name])
    assert error.value.code == 2
    assert github.commands == []
    assert not sync.BACKUP_ROOT.exists()


def test_apply_changes_only_titles_and_bodies_and_saves_full_originals(
    notes_dir: Path, github: GitHubProcess, tmp_path: Path
) -> None:
    """Successful updates preserve tags, assets, publication metadata, and complete originals."""
    github.backup_dir = sync.BACKUP_ROOT / "backups"
    github.releases[-1]["prerelease"] = True
    github.initial = deepcopy(github.releases)
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-name", github.backup_dir.name]) == 0
    for original, updated in zip(github.initial, github.releases, strict=True):
        assert updated == {
            **original,
            "name": original["tag_name"],
            "body": BODY.replace("v0.2.6", original["tag_name"]),
            "updated_at": "2026-10-12T00:00:00Z",
        }
        assert json.loads((github.backup_dir / f"{original['tag_name']}.json").read_text(encoding="utf-8")) == original


def test_bulk_apply_waits_one_second_after_previous_patch_completion(
    notes_dir: Path, github: GitHubProcess, tmp_path: Path
) -> None:
    """Fast reads cannot cause consecutive mutative requests to bypass GitHub's pacing guidance."""
    github.patch_duration = 0.2
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-name", "backups"]) == 0
    assert github.clock.sleeps == [1.0]
    assert github.patch_starts[1] - github.patch_finishes[0] >= 1.0
    assert [item["body"] for item in github.releases] == [BODY.replace("v0.2.6", "v0.2.5"), BODY]


def test_slow_verification_reads_count_toward_mutation_interval(
    notes_dir: Path, github: GitHubProcess, tmp_path: Path
) -> None:
    """Reads that already consume the required interval do not add redundant waiting."""
    github.read_duration = 1.1
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-name", "backups"]) == 0
    assert github.clock.sleeps == []
    assert github.patch_starts[1] - github.patch_finishes[0] >= 1.0


def test_specific_tag_leaves_other_releases_alone(notes_dir: Path, github: GitHubProcess, tmp_path: Path) -> None:
    """Selecting one version limits both mutations and backups to that release."""
    backups = sync.BACKUP_ROOT / "backups"
    assert sync.main(["--notes-dir", str(notes_dir), "--tag", "v0.2.6", "--apply", "--backup-name", backups.name]) == 0
    assert github.releases[0] == github.initial[0]
    assert github.releases[1]["name"] == "v0.2.6"
    assert sorted(path.name for path in backups.iterdir()) == ["v0.2.6.json"]


@pytest.mark.parametrize(
    "field,value",
    [("body", "Edited by someone else"), ("updated_at", "2026-10-11T00:00:00Z"), ("tag_name", "v0.2.4")],
)
def test_concurrent_changes_stop_before_patch(
    notes_dir: Path, github: GitHubProcess, tmp_path: Path, field: str, value: str
) -> None:
    """Freshly detected body, timestamp, or tag changes prevent the PATCH."""
    backups = sync.BACKUP_ROOT / "backups"
    github.conflict = {field: value}
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-name", backups.name]) == 1
    assert all(command[3] == "GET" for command in github.commands)
    assert len(list(backups.glob("*.json"))) == 2
    assert github.releases[0][field] == value


def test_initially_matching_release_is_revalidated_before_skipping(
    notes_dir: Path, github: GitHubProcess, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Concurrent edits to an initially matching release cannot produce a successful no-op apply."""
    for item in github.releases:
        item.update(name=item["tag_name"], body=BODY.replace("v0.2.6", item["tag_name"]))
    github.conflict = {"body": "A newer edit"}
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-name", "backups"]) == 1
    assert "release changed after preview" in capsys.readouterr().err
    assert github.releases[0]["body"] == "A newer edit"
    assert all(command[3] == "GET" for command in github.commands)
    assert github.clock.sleeps == []


def test_partial_failure_retains_all_backups_and_never_prints_credentials(
    notes_dir: Path, github: GitHubProcess, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Partial failures retain all originals and report the state without revealing CLI secrets."""
    github.backup_dir = sync.BACKUP_ROOT / "backups"
    github.fail_patch = 26
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-name", github.backup_dir.name]) == 1
    assert github.releases[0]["body"] == BODY.replace("v0.2.6", "v0.2.5")
    assert github.releases[1] == github.initial[1]
    assert len(list(github.backup_dir.glob("*.json"))) == 2
    output = capsys.readouterr()
    assert "ghp_secret" not in output.out + output.err
    assert "earlier updates" in output.err
    assert "auth status" in output.err


def test_existing_backup_is_never_overwritten(notes_dir: Path, github: GitHubProcess, tmp_path: Path) -> None:
    """Previous backup content survives an attempted reuse of its directory."""
    backups = sync.BACKUP_ROOT / "backups"
    backups.mkdir(parents=True)
    previous = backups / "v0.2.6.json"
    previous.write_text("previous original", encoding="utf-8")
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-name", backups.name]) == 1
    assert previous.read_text(encoding="utf-8") == "previous original"
    assert github.releases == github.initial


@pytest.mark.parametrize("tag", ["../escape", "v0.2.6/../../escape", r"..\escape", "/escape"])
def test_backup_helper_rejects_traversal_before_creating_any_files(tmp_path: Path, tag: str) -> None:
    """The backup helper validates its own filenames even when called without CLI selection."""
    backups = sync.BACKUP_ROOT / "backups"
    originals = {"v0.2.5": release(25, "v0.2.5"), tag: release(26, tag)}
    with pytest.raises(sync.SyncError, match="Invalid backup tag"):
        sync.backup_releases(backups.name, originals)
    assert not backups.exists()
    assert list(tmp_path.iterdir()) == []


def test_existing_empty_backup_directory_is_rejected(notes_dir: Path, github: GitHubProcess, tmp_path: Path) -> None:
    """Apply requires a new directory even when an existing destination is empty."""
    backups = sync.BACKUP_ROOT / "backups"
    backups.mkdir(parents=True)
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-name", backups.name]) == 1
    assert list(backups.iterdir()) == []
    assert github.releases == github.initial


@pytest.mark.parametrize("target_exists", [True, False])
def test_backup_directory_symlink_is_rejected(
    notes_dir: Path, github: GitHubProcess, tmp_path: Path, target_exists: bool
) -> None:
    """Neither existing nor dangling destination symlinks redirect release backups."""
    target = tmp_path / "target"
    if target_exists:
        target.mkdir()
    sync.BACKUP_ROOT.mkdir()
    backups = sync.BACKUP_ROOT / "backups"
    try:
        backups.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("Creating symlinks is unavailable in this test environment")
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-name", backups.name]) == 1
    assert backups.is_symlink()
    assert target.exists() == target_exists
    if target_exists:
        assert list(target.iterdir()) == []
    assert github.releases == github.initial


def test_named_backup_saves_only_version_files_inside_fixed_root() -> None:
    """Valid names select a new child under the fixed repository backup directory."""
    backups = sync.BACKUP_ROOT / "release-notes_20261012"
    original = release(26, "v0.2.6")
    sync.backup_releases(backups.name, {"v0.2.6": original})
    assert [path.name for path in backups.iterdir()] == ["v0.2.6.json"]
    assert json.loads((backups / "v0.2.6.json").read_text(encoding="utf-8")) == original


@pytest.mark.parametrize("name", ["../escape", "/outside", r"..\escape"])
def test_backup_helper_rejects_unsafe_names_without_filesystem_changes(tmp_path: Path, name: str) -> None:
    """Direct helper callers cannot bypass the fixed-root CLI boundary."""
    originals = {"v0.2.6": release(26, "v0.2.6")}
    with pytest.raises(sync.SyncError, match="Backup name"):
        sync.backup_releases(name, originals)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("target_exists", [True, False])
def test_fixed_backup_root_symlink_never_writes_outside_repository(
    notes_dir: Path, github: GitHubProcess, tmp_path: Path, target_exists: bool
) -> None:
    """A substituted root cannot redirect backup creation to an external directory."""
    outside = tmp_path / "outside"
    if target_exists:
        outside.mkdir()
    try:
        sync.BACKUP_ROOT.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("Creating symlinks is unavailable in this test environment")
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-name", "backups"]) == 1
    assert sync.BACKUP_ROOT.is_symlink()
    assert outside.exists() == target_exists
    if target_exists:
        assert list(outside.iterdir()) == []
    assert github.releases == github.initial


def test_verification_detects_changed_assets_and_stops_remaining_updates(
    notes_dir: Path, github: GitHubProcess, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A post-update asset mismatch halts synchronization before modifying the next release."""
    github.mutate_after_patch = {"assets": []}
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-name", "backups"]) == 1
    assert github.releases[1] == github.initial[1]
    assert "verification failed" in capsys.readouterr().err


def test_second_apply_is_idempotent(notes_dir: Path, github: GitHubProcess, tmp_path: Path) -> None:
    """Already synchronized releases require no further remote mutations."""
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-name", "first"]) == 0
    github.commands.clear()
    github.clock.sleeps.clear()
    assert sync.main(["--notes-dir", str(notes_dir), "--apply", "--backup-name", "second"]) == 0
    assert all(command[3] == "GET" for command in github.commands)
    assert github.clock.sleeps == []
