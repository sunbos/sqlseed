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
from html.parser import HTMLParser
from io import TextIOWrapper
from itertools import groupby, pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit

if TYPE_CHECKING:
    from collections.abc import Iterator

DEFAULT_REPO = "sunbos/sqlseed"
DEFAULT_NOTES_DIR = Path(__file__).resolve().parents[1] / ".github" / "release-notes"
# Preserve the original published collection while allowing newer notes to be added.
REQUIRED_HISTORICAL_TAGS = (
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
BACKUP_ROOT = Path(__file__).resolve().parents[1] / ".release-backups"
BACKUP_NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
TAG_PATTERN = re.compile(r"v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")
HTML_BLOCK_TAG_PATTERN = (
    "address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|dir|div|dl|dt|"
    "fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|head|header|hr|html|iframe|legend|li|link|"
    "main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|pre|script|search|section|source|style|summary|table|"
    "tbody|td|textarea|tfoot|th|thead|title|tr|track|ul"
)
INLINE_TOKEN = re.compile(r"\\[\\`<]|`+|<(?=[A-Za-z!/?])")
HTML_BLOCK_START = re.compile(r"</?(?:" + HTML_BLOCK_TAG_PATTERN + r")(?=[ \t/>]|$)", re.IGNORECASE)
INLINE_BLOCK_BOUNDARY = re.compile(
    r"\n(?:[ \t]*\n| {0,3}(?:>|[-+*][ \t]|1[.)][ \t]|<!--|</?(?:" + HTML_BLOCK_TAG_PATTERN + r")(?=[ \t/>]|\n)))",
    re.IGNORECASE,
)
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


class HTMLHeadingDetector(HTMLParser):
    """Reject actual heading tags while ignoring attributes, comments, and entities."""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Reject heading start tags, including self-closing forms delegated by HTMLParser."""
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            raise SyncError("HTML headings are not allowed; use the canonical ATX H2 and H3 headings")


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
    elif len(prefix) >= 3 and (prefix[0] != "`" or "`" not in tail):
        return prefix, tail
    return "", ""


def container_prefix(content: str) -> tuple[str, tuple[str, int]] | None:
    """Remove one quote/list marker while preserving four-space code indentation."""
    if ends_setext_paragraph(content):
        return None
    if match := re.match(r" {0,3}> ?", content):
        return content[match.end() :], ("quote", 0)
    if match := re.match(r" {0,3}(?:[-+*]|\d{1,9}[.)]) +", content):
        whitespace = len(match[0]) - len(match[0].rstrip(" "))
        width = match.end() - whitespace + (1 if whitespace > 4 else whitespace)
        return content[width:], ("list", width)
    return None


def continue_container(content: str, frame: tuple[str, int]) -> str | None:
    """Match a quote prefix or a list item's relative continuation indentation."""
    kind, width = frame
    if kind == "quote":
        match = re.match(r" {0,3}> ?", content)
        return content[match.end() :] if match else None
    if not content.strip():
        return ""
    return content[width:] if content.startswith(" " * width) else None


def container_content(
    line: str, active: tuple[tuple[str, int], ...], literal: bool
) -> tuple[str, tuple[tuple[str, int], ...], bool]:
    """Follow existing containers and recognize new ones outside literal code/HTML."""
    content = line.expandtabs(4)
    frames = []
    for frame in active:
        continued = continue_container(content, frame)
        if continued is None:
            break
        frames.append(frame)
        content = continued
    interrupted = len(frames) != len(active)
    if literal and not interrupted:
        return content, tuple(frames), False
    while prefix := container_prefix(content):
        content, frame = prefix
        frames.append(frame)
    context = tuple(frames)
    return content, context, interrupted or context != active


def markdown_content_kind(content: str, marker: str, raw_html: bool, paragraph: bool) -> tuple[str, bool]:
    """Keep indented code distinct from ordinary paragraph continuation lines."""
    if raw_html:
        return "html", False
    if marker.startswith("#"):
        return "heading", False
    if content.startswith("    ") and not paragraph:
        return "code", False
    return "prose", bool(content.strip())


def markdown_line_kinds(lines: list[str]) -> Iterator[tuple[int, str, str, int]]:
    """Classify lines with fenced code taking precedence over raw HTML blocks."""
    fence = ""
    html_end = None
    context: tuple[tuple[str, int], ...] = ()
    context_id = 0
    paragraph = False
    for index, line in enumerate(lines):
        content, context, changed = container_content(line, context, bool(fence or html_end is not None))
        if changed:
            fence, html_end, paragraph = "", None, False
            context_id += 1
        marker, tail = markdown_prefix(content)
        if fence:
            if marker.startswith(fence[0]) and len(marker) >= len(fence) and not tail.strip():
                fence = ""
            else:
                yield index, "code", content, context_id
            continue
        raw_html, html_end = html_block_state(content, html_end, not paragraph)
        if not raw_html and marker.startswith(("`", "~")):
            fence = marker
            paragraph = False
            continue
        kind, paragraph = markdown_content_kind(content, marker, raw_html, paragraph)
        yield index, kind, content, context_id
    if fence:
        raise SyncError("Release notes contain an unclosed fenced code block")


def markdown_structure(lines: list[str]) -> tuple[list[tuple[int, str]], set[int], set[int], set[int]]:
    """Locate headings, content, unfenced content, and lines in raw HTML blocks."""
    headings = []
    content_lines = set()
    unfenced_lines = set()
    html_lines = set()
    rendered_lines = lines.copy()
    nested_lines = set()
    context_lines: dict[int, set[int]] = {}
    for index, kind, content, context_id in markdown_line_kinds(lines):
        rendered_lines[index] = content
        if content != lines[index]:
            nested_lines.add(index)
        if kind == "html":
            html_lines.add(index)
        if kind == "heading":
            headings.append((index, lines[index]))
        elif lines[index].strip():
            content_lines.add(index)
            if kind != "code":
                unfenced_lines.add(index)
                context_lines.setdefault(context_id, set()).add(index)
    validate_nested_setext(rendered_lines, nested_lines, context_lines, html_lines)
    return headings, content_lines, unfenced_lines, html_lines


def validate_nested_setext(
    lines: list[str], nested_lines: set[int], context_lines: dict[int, set[int]], html_lines: set[int]
) -> None:
    """Require a paragraph within the same container before interpreting a Setext underline."""
    for context in context_lines.values():
        if any(is_setext_heading(lines, index, context) for index in nested_lines & context - html_lines):
            raise SyncError("Nested Setext headings are not allowed; use the canonical ATX H2 and H3 headings")


def is_template_instruction(line: str) -> bool:
    """Match standalone template prose while preserving indented code examples."""
    if line.startswith("    ") or line.lstrip(" ").startswith("\t"):
        return False
    normalized = " ".join(line.split()).removeprefix("- ")
    return normalized in TEMPLATE_INSTRUCTIONS


def is_setext_underline(line: str) -> bool:
    """Recognize a Setext underline with at most three leading spaces."""
    if line.startswith("    ") or line.lstrip(" ").startswith("\t"):
        return False
    content = line.strip()
    return bool(content) and content[0] in "=-" and not content.strip(content[0])


def ends_setext_paragraph(line: str) -> bool:
    """Treat thematic breaks and link definitions as paragraph boundaries."""
    content = line.strip()
    compact = content.replace(" ", "").replace("\t", "")
    return (len(compact) >= 3 and compact[0] in "-*_" and not compact.strip(compact[0])) or (
        content.startswith("[") and "]:" in content
    )


def is_setext_heading(lines: list[str], index: int, unfenced_lines: set[int]) -> bool:
    """Find extra top-level Setext sections without mistaking list or quote separators for headings."""
    if not is_setext_underline(lines[index]):
        return False
    start = index - 1
    has_paragraph = False
    while start in unfenced_lines:
        previous = lines[start]
        if previous.startswith("    ") or previous.lstrip(" ").startswith("\t"):
            # Indented lines can continue a paragraph but cannot begin one.
            start -= 1
            continue
        if ends_setext_paragraph(previous):
            break
        content = previous.lstrip(" ")
        if (
            content.startswith(">")
            or starts_html_block(content)
            or re.match(r"(?:[-+*]|\d{1,9}[.)])(?:[ \t]|$)", content)
        ):
            return False
        has_paragraph = True
        start -= 1
    return has_paragraph


def html_prose(lines: list[str], unfenced_lines: set[int], html_lines: set[int]) -> str:
    """Keep prose and indented paragraph continuations, excluding standalone code."""
    prose = []
    paragraph = False
    for index, line in enumerate(lines):
        indented = line.startswith("    ") or line.lstrip(" ").startswith("\t")
        paragraph = index in html_lines or (index in unfenced_lines and (paragraph or not indented))
        prose.append(line if paragraph else "")
    parts = []
    for raw_html, group in groupby(enumerate(prose), key=lambda item: item[0] in html_lines):
        text = "\n".join(line for _, line in group) + "\n"
        parts.append(text if raw_html else without_inline_examples(text))
    return "".join(parts)


def html_token_end(text: str, start: int) -> int:
    """Preserve complete HTML tokens so attribute backticks cannot start Markdown code."""
    if text.startswith("<!--", start):
        end = text.find("-->", start + 4)
        return len(text) if end < 0 else end + 3
    quote = ""
    for index in range(start + 1, len(text)):
        character = text[index]
        if quote:
            if character == quote:
                quote = ""
        elif character in "\"'":
            quote = character
        elif character == ">":
            return index + 1
    return start + 1


def starts_html_block(content: str) -> bool:
    """Separate actual HTML blocks from autolinks and inline HTML paragraphs."""
    if content.startswith(("<!--", "<?", "<![CDATA[")) or re.match(r"<![A-Z]", content):
        return True
    if HTML_BLOCK_START.match(content):
        return True
    return bool(re.match(r"</?[A-Za-z][A-Za-z0-9-]*(?=[ \t/>])", content)) and html_token_end(content, 0) == len(
        content.rstrip()
    )


def html_block_ending(line: str, paragraph_boundary: bool) -> str | None:
    """Identify raw HTML blocks by their standard closing token or a blank line."""
    content = line.lstrip(" ")
    if len(line) - len(content) > 3:
        return None
    for prefix, ending in (("<!--", "-->"), ("<?", "?>"), ("<![CDATA[", "]]>")):
        if content.startswith(prefix):
            return ending
    if match := re.match(r"<(script|pre|style|textarea)(?=[ \t>]|$)", content, re.IGNORECASE):
        return f"</{match[1]}>"
    if re.match(r"<![A-Z]", content):
        return ">"
    if HTML_BLOCK_START.match(content) or (paragraph_boundary and starts_html_block(content)):
        return ""
    return None


def html_block_state(line: str, ending: str | None, paragraph_boundary: bool) -> tuple[bool, str | None]:
    """Keep Markdown-looking characters literal until a raw HTML block ends."""
    if ending is None:
        ending = html_block_ending(line, paragraph_boundary)
    if ending is None:
        return False, None
    if not ending:
        return bool(line.strip()), "" if line.strip() else None
    return True, None if ending.lower() in line.lower() else ending


def inline_code_end(text: str, opening: re.Match[str]) -> int:
    """Find an exact backtick run before a paragraph or HTML block boundary."""
    for closing in re.finditer(r"`+", text[opening.end() :]):
        if len(closing[0]) != len(opening[0]):
            continue
        end = opening.end() + closing.end()
        if INLINE_BLOCK_BOUNDARY.search(text, opening.end(), end):
            break
        return end
    return opening.end()


def without_inline_examples(text: str) -> str:
    """Mask Markdown code spans and escaped angle brackets before parsing raw HTML."""
    parts = []
    position = 0
    while match := INLINE_TOKEN.search(text, position):
        parts.append(text[position : match.start()])
        token = match[0]
        if token.startswith("\\"):
            parts.append(" " if token == "\\<" else token[1:])
            position = match.end()
        elif token == "<":
            position = html_token_end(text, match.start())
            parts.append(text[match.start() : position])
        else:
            position = inline_code_end(text, match)
            parts.append(token if position == match.end() else " ")
    parts.append(text[position:])
    return "".join(parts)


def read_notes(path: Path) -> str:
    """Read notes and templates using the same canonical UTF-8 and newline rules."""
    try:
        body = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise SyncError(f"Cannot read UTF-8 notes: {path}") from exc
    if body.startswith("\ufeff") or "\r" in body or not body.endswith("\n"):
        raise SyncError(f"{path}: use UTF-8 without BOM, LF line endings, and a final newline")
    return body


def validate_note_structure(path: Path, body: str, *, template: bool = False) -> str:
    """Validate the shared bilingual structure and return the final links section."""
    lines = body.splitlines()
    headings, content_lines, unfenced_lines, html_lines = markdown_structure(lines)
    HTMLHeadingDetector().feed(html_prose(lines, unfenced_lines, html_lines))
    if any(is_setext_heading(lines, index, unfenced_lines) for index in unfenced_lines - html_lines):
        raise SyncError(f"{path}: Setext headings are not allowed; use the canonical ATX H2 and H3 headings")
    if not template and any(is_template_instruction(lines[index]) for index in unfenced_lines):
        raise SyncError(f"{path}: replace release-template instructions with version-specific release notes")
    validate_sections(path, lines, headings, content_lines)
    if template:
        subsections = [heading[4:] for _, heading in headings if heading.startswith("### ")]
        if subsections != [*SUBSECTIONS, *SUBSECTIONS.values()]:
            raise SyncError(f"{path}: template must include all English/Chinese subsections in canonical order")
    return "\n".join(lines[headings[-1][0] + 1 :])


def validate_notes(path: Path, repo: str = DEFAULT_REPO) -> str:
    """Read canonical UTF-8 notes and check their bilingual section structure."""
    body = read_notes(path)
    if "vVERSION" in body or "vPREVIOUS" in body:
        raise SyncError(f"{path}: replace release-template version placeholders")
    links = validate_note_structure(path, body)
    validate_versioned_links(path, links, repo)
    return body


def validate_template(path: Path, repo: str = DEFAULT_REPO) -> None:
    """Keep the complete canonical template while allowing its instructions and placeholders."""
    links = validate_note_structure(path, read_notes(path), template=True)
    validate_versioned_links(path, links, repo, expected_tag="vVERSION")


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


def validate_versioned_links(path: Path, links: str, repo: str, *, expected_tag: str | None = None) -> None:
    """Require a tagged source root and keep final versioned links on the note's tag."""
    expected_tag = path.stem if expected_tag is None else expected_tag
    source_found = False
    for match in re.finditer(r"https?://github\.com/[^\s<>)\"']+", links):
        parts = unquote(urlsplit(match[0]).path).strip("/").split("/")
        if parts[:2] != repo.split("/") or len(parts) < 4 or parts[2] not in {"tree", "blob", "compare"}:
            continue
        target = parts[3].rsplit("...", 1)[-1] if parts[2] == "compare" else parts[3]
        if target != expected_tag:
            raise SyncError(f"{path}: release link target {target!r} must match {expected_tag}")
        if parts[2] == "tree" and len(parts) == 4:
            source_found = True
    if not source_found:
        raise SyncError(
            f"{path}: links section must include a source link to https://github.com/{repo}/tree/{expected_tag}"
        )


def validate_collection(directory: Path, selected: list[str], repo: str) -> None:
    """Protect the default historical inventory and validate any supplied template."""
    default_directory = directory.resolve() == DEFAULT_NOTES_DIR.resolve()
    if default_directory and repo == DEFAULT_REPO:
        missing = [tag for tag in REQUIRED_HISTORICAL_TAGS if tag not in selected]
        if missing:
            raise SyncError(f"Missing required historical release notes in {directory}: {', '.join(missing)}")
    template = directory / "TEMPLATE.md"
    if default_directory or template.exists():
        validate_template(template, repo)


def load_notes(directory: Path, tags: list[str] | None, repo: str = DEFAULT_REPO) -> dict[str, str]:
    """Validate selected version filenames and their contents before contacting GitHub."""
    selected = tags if tags is not None else [path.stem for path in directory.glob("v*.md")]
    if tags is None:
        validate_collection(directory, selected, repo)
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


def configure_output() -> None:
    """Keep bilingual diffs and error paths readable when a shell defaults to ASCII."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def main(argv: list[str] | None = None) -> int:
    """Run offline validation, default preview, or an explicitly requested update."""
    configure_output()
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
