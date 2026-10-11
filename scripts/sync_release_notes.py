#!/usr/bin/env python3
"""Preview or update the titles and bilingual notes of existing GitHub releases."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
import time
from itertools import pairwise
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

DEFAULT_REPO = "sunbos/sqlseed"
DEFAULT_NOTES_DIR = Path(__file__).resolve().parents[1] / ".github" / "release-notes"
BACKUP_ROOT = Path(__file__).resolve().parents[1] / ".release-backups"
BACKUP_NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
TAG_PATTERN = re.compile(r"v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")
HEADINGS = ["## English", "## 中文", "## Links / 相关链接"]
SUBSECTIONS = {
    "Added": "新增",
    "Changed": "变更",
    "Fixed": "修复",
    "Removed": "移除",
    "Compatibility": "兼容性",
    "Verification": "验收记录",
}
TEMPLATE_INSTRUCTIONS = (
    "Describe a user-visible addition.",
    "Describe a behavior or maintenance change.",
    "Describe the trigger and corrected behavior.",
    "Describe a removal and its replacement, if any.",
    "Record version-specific upgrade steps and support limits.",
    "Link evidence for this version; distinguish historical records from new checks.",
    "描述用户可见的新增能力。",
    "描述行为或维护方式的变化。",
    "描述问题的触发条件与修复后的行为。",
    "描述移除内容及替代方式（如有）。",
    "记录本版本的升级步骤与支持边界。",
    "链接本版本的验收依据，区分历史记录与新执行的检查。",
)
INVARIANT_FIELDS = (
    "id",
    "tag_name",
    "target_commitish",
    "draft",
    "prerelease",
    "created_at",
    "published_at",
    "immutable",
)


class SyncError(RuntimeError):
    """A validation, remote API, or concurrency failure that stops synchronization."""


def markdown_prefix(line: str) -> tuple[str, str]:
    """Recognize a heading or code-fence prefix in linear time without backtracking."""
    content = line.lstrip(" ")
    if len(line) - len(content) > 3 or not content or content[0] not in "#`~":
        return "", ""
    tail = content.lstrip(content[0])
    prefix = content[: len(content) - len(tail)]
    if prefix[0] == "#":
        if len(prefix) <= 6 and (not tail or tail[0].isspace()):
            return prefix, tail
    elif len(prefix) >= 3:
        return prefix, tail
    return "", ""


def markdown_structure(lines: list[str]) -> tuple[list[tuple[int, str]], set[int], set[int]]:
    """Locate headings, nonblank content, and content outside fenced code."""
    headings = []
    content_lines = set()
    unfenced_lines = set()
    fence = ""
    for index, line in enumerate(lines):
        marker, tail = markdown_prefix(line)
        if fence:
            if marker.startswith(fence[0]) and len(marker) >= len(fence) and not tail.strip():
                fence = ""
            elif line.strip():
                content_lines.add(index)
            continue
        if marker.startswith(("`", "~")):
            fence = marker
        elif marker.startswith("#"):
            headings.append((index, line))
        elif line.strip():
            content_lines.add(index)
            unfenced_lines.add(index)
    if fence:
        raise SyncError("Release notes contain an unclosed fenced code block")
    return headings, content_lines, unfenced_lines


def is_template_instruction(line: str) -> bool:
    """Match standalone template prose while preserving indented code examples."""
    if line.startswith("    ") or line.lstrip(" ").startswith("\t"):
        return False
    normalized = " ".join(line.split()).removeprefix("- ")
    return normalized in TEMPLATE_INSTRUCTIONS


def validate_notes(path: Path, repo: str = DEFAULT_REPO) -> str:
    """Read canonical UTF-8 notes and check their bilingual section structure."""
    try:
        body = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise SyncError(f"Cannot read UTF-8 notes: {path}") from exc
    if body.startswith("\ufeff") or "\r" in body or not body.endswith("\n"):
        raise SyncError(f"{path}: use UTF-8 without BOM, LF line endings, and a final newline")
    if "vVERSION" in body or "vPREVIOUS" in body:
        raise SyncError(f"{path}: replace release-template version placeholders")
    lines = body.splitlines()
    headings, content_lines, unfenced_lines = markdown_structure(lines)
    if any(is_template_instruction(lines[index]) for index in unfenced_lines):
        raise SyncError(f"{path}: replace release-template instructions with version-specific release notes")
    validate_sections(path, lines, headings, content_lines)
    validate_versioned_links(path, "\n".join(lines[headings[-1][0] + 1 :]), repo)
    return body


def validate_sections(path: Path, lines: list[str], headings: list[tuple[int, str]], content_lines: set[int]) -> None:
    """Require canonical bilingual headings and nonempty ordered subsections."""
    if any(not heading.startswith(("## ", "### ")) for _, heading in headings):
        raise SyncError(f"{path}: only unindented H2 and H3 headings are allowed outside code blocks")
    if [heading for _, heading in headings if heading.startswith("## ")] != HEADINGS:
        raise SyncError(f"{path}: expected exactly these headings in order: {', '.join(HEADINGS)}")
    if lines[0] != HEADINGS[0]:
        raise SyncError(f"{path}: notes must start with {HEADINGS[0]}")
    positions = [index for index, heading in headings if heading.startswith("## ")] + [len(lines)]
    if any(not any(start < index < end for index in content_lines) for start, end in pairwise(positions)):
        raise SyncError(f"{path}: English, Chinese, and links sections must be nonempty")
    english = [heading[4:] for index, heading in headings if positions[0] < index < positions[1]]
    chinese = [heading[4:] for index, heading in headings if positions[1] < index < positions[2]]
    if (
        not english
        or english != [section for section in SUBSECTIONS if section in english]
        or chinese != [SUBSECTIONS.get(section) for section in english]
        or any(index > positions[2] for index, _ in headings)
    ):
        raise SyncError(f"{path}: require matching English/Chinese subsections in canonical order")
    for (start, heading), (end, _) in pairwise([*headings, (len(lines), "")]):
        if heading.startswith("### ") and not any(start < index < end for index in content_lines):
            raise SyncError(f"{path}: {heading} must contain nonwhitespace content")


def validate_versioned_links(path: Path, links: str, repo: str) -> None:
    """Require this repository's final source and comparison links to target the note's tag."""
    for match in re.finditer(r"https?://github\.com/[^\s<>)\"']+", links):
        parts = unquote(urlsplit(match[0]).path).strip("/").split("/")
        if parts[:2] != repo.split("/") or len(parts) < 4 or parts[2] not in {"tree", "blob", "compare"}:
            continue
        target = parts[3].rsplit("...", 1)[-1] if parts[2] == "compare" else parts[3]
        if target != path.stem:
            raise SyncError(f"{path}: release link target {target!r} must match {path.stem}")


def load_notes(directory: Path, tags: list[str] | None, repo: str = DEFAULT_REPO) -> dict[str, str]:
    """Validate selected version filenames and their contents before contacting GitHub."""
    selected = tags if tags is not None else [path.stem for path in directory.glob("v*.md")]
    if not selected:
        raise SyncError(f"No version notes found in {directory}")
    if len(selected) != len(set(selected)):
        raise SyncError("Each --tag must be specified only once")
    for tag in selected:
        if not TAG_PATTERN.fullmatch(tag):
            raise SyncError(f"Invalid version tag: {tag!r}; expected vX.Y.Z")
    ordered = sorted(selected, key=lambda tag: tuple(int(part) for part in tag[1:].split(".")))
    return {tag: validate_notes(directory / f"{tag}.md", repo) for tag in ordered}


def github_api(endpoint: str, *, payload: dict[str, str] | None = None, paginate: bool = False) -> Any:
    """Run gh without a shell, withholding stderr because it can contain credentials."""
    command = ["gh", "api", "--method", "PATCH" if payload is not None else "GET", endpoint]
    if paginate:
        command.extend(["--paginate", "--slurp"])
    if payload is not None:
        command.extend(["--input", "-"])
    try:
        result = subprocess.run(
            command,
            input=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
            encoding="utf-8",
            capture_output=True,
            check=False,
            timeout=120,
        )
    except FileNotFoundError as exc:
        raise SyncError("GitHub CLI (gh) is not installed or is not on PATH") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SyncError("GitHub API command could not complete; check connectivity and retry the preview") from exc
    if result.returncode:
        raise SyncError(
            f"GitHub API {command[3]} failed (gh exit {result.returncode}); "
            "check network access and `gh auth status`. A failed PATCH may already have reached GitHub; "
            "inspect the release before retrying. CLI stderr was withheld to avoid exposing credentials."
        )
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise SyncError("GitHub CLI returned invalid JSON; synchronization stopped") from exc


def validate_release(release: Any) -> dict[str, Any]:
    """Require the API fields used for conflict detection and preservation checks."""
    required = set(INVARIANT_FIELDS) - {"immutable"} | {"name", "body", "updated_at", "assets"}
    if not isinstance(release, dict) or required.difference(release):
        raise SyncError("GitHub returned an incomplete release record")
    if not isinstance(release["id"], int) or not isinstance(release["assets"], list):
        raise SyncError("GitHub returned an invalid release ID or assets list")
    if any(not isinstance(asset, dict) or not isinstance(asset.get("id"), int) for asset in release["assets"]):
        raise SyncError("GitHub returned an invalid asset record")
    return release


def preservation_fields(release: dict[str, Any]) -> dict[str, Any]:
    """Capture release identity, publication state, target, and attached asset identities."""
    return {
        **{field: release.get(field) for field in INVARIANT_FIELDS},
        "asset_ids": sorted(asset["id"] for asset in release["assets"]),
    }


def select_releases(repo: str, notes: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Require one existing, published release for every selected local version."""
    pages = github_api(f"repos/{repo}/releases?per_page=100", paginate=True)
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise SyncError("GitHub CLI returned an invalid paginated release list")
    releases = [validate_release(release) for page in pages for release in page]
    selected = {}
    for tag in notes:
        matches = [release for release in releases if release["tag_name"] == tag]
        if len(matches) != 1 or matches[0]["draft"]:
            raise SyncError(f"{tag}: expected exactly one existing non-draft GitHub release")
        selected[tag] = matches[0]
    return selected


def preview(notes: dict[str, str], releases: dict[str, dict[str, Any]]) -> None:
    """Print the proposed name and body differences without performing writes."""
    for tag, body in notes.items():
        original = releases[tag]
        changed = original["name"] != tag or original["body"] != body
        print(f"{tag}: {'would update' if changed else 'already matches'}")
        if original["name"] != tag:
            print(f"  title: {original['name']!r} -> {tag!r}")
        if original["body"] != body:
            print(
                "".join(
                    difflib.unified_diff(
                        (original["body"] or "").splitlines(keepends=True),
                        body.splitlines(keepends=True),
                        fromfile=f"GitHub/{tag}",
                        tofile=f"notes/{tag}.md",
                    )
                ),
                end="",
            )


def backup_releases(name: str, releases: dict[str, dict[str, Any]]) -> None:
    """Save every full original JSON record before the first remote mutation."""
    if not BACKUP_NAME_PATTERN.fullmatch(name):
        raise SyncError("Backup name must contain only ASCII letters, digits, '-' and '_'")
    for tag in releases:
        if not TAG_PATTERN.fullmatch(tag):
            raise SyncError(f"Invalid backup tag: {tag!r}; expected vX.Y.Z")
    if BACKUP_ROOT.is_symlink():
        raise SyncError("The repository .release-backups directory must not be a symlink")
    BACKUP_ROOT.mkdir(mode=0o700, exist_ok=True)
    if BACKUP_ROOT.resolve(strict=True) != BACKUP_ROOT:
        raise SyncError("The repository backup root must not traverse a symlink")
    directory = BACKUP_ROOT / name
    try:
        directory.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError as exc:
        raise SyncError("Backup already exists; choose a new --backup-name") from exc
    backup_root = directory.resolve(strict=True)
    if backup_root.parent != BACKUP_ROOT:
        raise SyncError("Backup directory must stay inside the repository backup root")
    for tag, release in releases.items():
        output = (backup_root / f"{tag}.json").resolve()
        if output.parent != backup_root:
            raise SyncError("Backup output must stay inside the selected backup directory")
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(release, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    print(f"Backed up {len(releases)} complete release records to {directory}")


def wait_before_mutation(previous_finished: float | None) -> None:
    """Leave at least one second after the previous PATCH before checking the next release."""
    if previous_finished is not None:
        delay = 1.0 - (time.monotonic() - previous_finished)
        if delay > 0:
            time.sleep(delay)


def apply_notes(repo: str, notes: dict[str, str], releases: dict[str, dict[str, Any]]) -> None:
    """Apply only name/body, stopping on concurrent edits or failed preservation checks."""
    last_patch_finished = None
    for tag, body in notes.items():
        original = releases[tag]
        needs_update = original["name"] != tag or original["body"] != body
        if needs_update:
            wait_before_mutation(last_patch_finished)
        endpoint = f"repos/{repo}/releases/{original['id']}"
        fresh = validate_release(github_api(endpoint))
        if any(fresh[key] != original[key] for key in ("name", "body", "updated_at")) or preservation_fields(
            fresh
        ) != preservation_fields(original):
            raise SyncError(f"{tag}: release changed after preview; no update applied to this release")
        if not needs_update:
            print(f"{tag}: already matches")
            continue
        # Like `gh release edit`, carry the existing tag: GitHub can detach it if omitted.
        # Intentionally omit every other API parameter, including make_latest.
        github_api(endpoint, payload={"name": tag, "body": body, "tag_name": original["tag_name"]})
        last_patch_finished = time.monotonic()
        updated = validate_release(github_api(endpoint))
        if (
            updated["name"] != tag
            or updated["body"] != body
            or preservation_fields(updated) != preservation_fields(original)
        ):
            raise SyncError(f"{tag}: verification failed after PATCH; inspect the release and its original backup")
        print(f"{tag}: updated and verified")


def main(argv: list[str] | None = None) -> int:
    """Run offline validation, default preview, or an explicitly requested update."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="validate local notes without invoking gh")
    mode.add_argument("--apply", action="store_true", help="update existing release titles and bodies")
    parser.add_argument("--tag", action="append", help="select vX.Y.Z; repeat to select several versions")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub owner/repository")
    parser.add_argument("--notes-dir", type=Path, default=DEFAULT_NOTES_DIR)
    parser.add_argument(
        "--backup-name",
        help="required for --apply: unique ASCII letters/digits/-/_ name under repository .release-backups",
    )
    args = parser.parse_args(argv)
    if args.apply and args.backup_name is None:
        parser.error("--apply requires --backup-name")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        parser.error("--repo must be owner/repository")
    if args.backup_name is not None and not BACKUP_NAME_PATTERN.fullmatch(args.backup_name):
        parser.error("--backup-name must contain only ASCII letters, digits, '-' and '_'")
    try:
        notes = load_notes(args.notes_dir, args.tag, args.repo)
        if args.check:
            print(f"Validated {len(notes)} local release notes; no GitHub access")
            return 0
        releases = select_releases(args.repo, notes)
        preview(notes, releases)
        if args.apply:
            backup_releases(args.backup_name, releases)
            apply_notes(args.repo, notes, releases)
        else:
            print("Preview only; no releases changed. Use --apply --backup-name NAME to update.")
    except (SyncError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if args.apply:
            print(
                "Stopped without automatic rollback. "
                f"Inspect remote state and backups in {BACKUP_ROOT / args.backup_name} "
                "before retrying; earlier updates, if any, remain applied.",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
