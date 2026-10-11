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
import unicodedata
from html.parser import HTMLParser
from io import TextIOWrapper
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit

if TYPE_CHECKING:
    from collections.abc import Iterator

    from markdown_it.token import Token

try:
    from markdown_it import MarkdownIt
except ImportError:
    print(
        "Release-note validation requires its pinned Markdown parser. In a virtual environment, run:\n"
        "python -m pip install --require-hashes --only-binary :all: -r .github/requirements-release-notes.txt",
        file=sys.stderr,
    )
    raise SystemExit(1) from None

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


def markdown_parser() -> MarkdownIt:
    """Use one CommonMark configuration with GitHub's single/double-tilde strikethrough."""
    return MarkdownIt("commonmark", {"strikethrough_single_tilde": True}).enable("strikethrough")


class HTMLHeadingDetector(HTMLParser):
    """Reject actual heading tags while ignoring attributes, comments, and entities."""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Reject heading start tags, including self-closing forms delegated by HTMLParser."""
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            raise SyncError("HTML headings are not allowed; use the canonical ATX H2 and H3 headings")


def visible_text(text: str) -> bool:
    """Ignore whitespace and formatting-only characters when looking for visible text."""
    return any(not character.isspace() and unicodedata.category(character) != "Cf" for character in text)


class VisibleContentDetector(HTMLParser):
    """Recognize rendered text and visual elements, ignoring comments and empty tags."""

    def __init__(self) -> None:
        """Start without visible content; HTMLParser decodes character references."""
        super().__init__()
        self.visible = False

    def handle_data(self, data: str) -> None:
        """Record nonwhitespace text outside HTML attributes and comments."""
        self.visible |= visible_text(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Keep image and horizontal-rule content even when it has no text node."""
        if tag in {"img", "hr"}:
            self.visible = True


def markdown_headings(lines: list[str], tokens: list[Token]) -> list[tuple[int, str]]:
    """Use CommonMark heading tokens while retaining the exact canonical source lines."""
    headings = []
    for token in tokens:
        if token.type != "heading_open" or token.map is None:
            continue
        if not token.markup.startswith("#"):
            raise SyncError("Setext headings are not allowed; use the canonical ATX H2 and H3 headings")
        if token.level:
            raise SyncError("Nested headings are not allowed; use the canonical ATX H2 and H3 headings")
        headings.append((token.map[0], lines[token.map[0]]))
    return headings


def validate_fenced_blocks(tokens: list[Token]) -> None:
    """Require explicit closing delimiters for fences that are not bounded by a container."""
    for token in tokens:
        if (
            token.type == "fence"
            and token.level == 0
            and token.map is not None
            and token.map[1] - token.map[0] != len(token.content.splitlines()) + 2
        ):
            raise SyncError("Release notes contain an unclosed fenced code block")


def raw_html_fragments(tokens: list[Token]) -> Iterator[str]:
    """Read only actual raw HTML tokens, excluding Markdown code and escaped examples."""
    for token in tokens:
        if token.type == "html_block":
            yield token.content
        for child in token.children or []:
            if child.type == "html_inline":
                yield child.content


class TemplateProseDetector(HTMLParser):
    """Read formatted prose while keeping code and quotation examples separate."""

    def __init__(self) -> None:
        """Start with plain prose and no enclosing literal element."""
        super().__init__()
        self.parts: list[str] = []
        self.literal_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Make formatting transparent and preserve code, quotes, and line boundaries."""
        if tag in {"code", "pre", "q", "blockquote"}:
            self.literal_tags.append(tag)
            self.parts.append("\0")
        elif tag in {"br", "div", "li", "p"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        """Resume prose when the corresponding literal element closes."""
        if self.literal_tags and self.literal_tags[-1] == tag:
            self.literal_tags.pop()
        if tag in {"div", "li", "p"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        """Collapse source line wraps while explicit rendered boundaries stay separate."""
        if not self.literal_tags:
            self.parts.append(data.replace("\n", " "))


def has_template_instructions(tokens: list[Token]) -> bool:
    """Find complete template prose lines while allowing quotations and code examples."""
    quote_depth = 0
    for index, token in enumerate(tokens):
        if token.type == "blockquote_open":
            quote_depth += 1
        elif token.type == "blockquote_close":
            quote_depth -= 1
        elif token.type in {"inline", "html_block"} and not quote_depth:
            text = template_prose(token)
            if is_task_list_prose(tokens, index):
                text = re.sub(r"^\[[ xX]\]\s+", "", text, count=1)
            if any(" ".join(line.split()) in TEMPLATE_INSTRUCTIONS for line in text.splitlines()):
                return True
    return False


def is_task_list_prose(tokens: list[Token], index: int) -> bool:
    """Recognize a checkbox only at the start of a list item's first paragraph."""
    return (
        index >= 2
        and tokens[index - 2].type == "list_item_open"
        and tokens[index - 1].type == "paragraph_open"
        and re.match(r"^\[[ xX]\][ \t\n]+", tokens[index].content) is not None
    )


def template_prose(token: Token) -> str:
    """Read rendered prose consistently for Markdown formatting and raw HTML blocks."""
    markdown = markdown_parser()
    parser = TemplateProseDetector()
    rendered = markdown.renderer.render([token], markdown.options, {})
    parser.feed(rendered)
    return "".join(parser.parts)


def markdown_content_lines(tokens: list[Token], headings: list[tuple[int, str]]) -> set[int]:
    """Retain source-content positions for structure and existing empty-subsection diagnostics."""
    heading_lines = {index for index, _ in headings}
    return {
        token.map[0]
        for token in tokens
        if token.map is not None and token.map[0] not in heading_lines and (token.content.strip() or token.type == "hr")
    }


def has_visible_content(lines: list[str]) -> bool:
    """Render CommonMark so code, images, entities, and reference links share one interpretation."""
    parser = VisibleContentDetector()
    parser.feed(markdown_parser().render("\n".join(lines)))
    return parser.visible


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
    tokens = markdown_parser().parse(body)
    headings = markdown_headings(lines, tokens)
    detector = HTMLHeadingDetector()
    for fragment in raw_html_fragments(tokens):
        detector.feed(fragment)
    validate_fenced_blocks(tokens)
    if not template and has_template_instructions(tokens):
        raise SyncError(f"{path}: replace release-template instructions with version-specific release notes")
    content_lines = markdown_content_lines(tokens, headings)
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
        if heading.startswith("### "):
            validate_subsection_content(
                path, heading, lines[start + 1 : end], any(start < index < end for index in content_lines)
            )


def validate_subsection_content(path: Path, heading: str, lines: list[str], source_content: bool) -> None:
    """Keep the existing empty-source diagnostic and reject visually empty markup separately."""
    if not source_content:
        raise SyncError(f"{path}: {heading} must contain nonwhitespace content")
    if not has_visible_content(lines):
        raise SyncError(f"{path}: {heading} must contain visible content")


class HTMLSourceLinks(HTMLParser):
    """Collect anchors with visible labels and track text that cannot become an autolink."""

    LITERAL_TAGS = frozenset({"a", "code", "pre", "script", "style", "textarea", "title"})
    HIDDEN_TAGS = frozenset({"script", "style", "textarea", "title"})

    def __init__(self) -> None:
        """Keep anchor state separate from literal HTML text contexts."""
        super().__init__()
        self.targets: list[str] = []
        self.context: list[str] = []
        self.href: str | None = None
        self.visible = False

    def finish_anchor(self) -> None:
        """Ignore empty anchor elements, which provide no clickable reference."""
        if self.href and self.visible:
            self.targets.append(self.href)
        self.href, self.visible = None, False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Only href on an anchor can supply a link; image and other attributes cannot."""
        attributes = dict(attrs)
        if tag == "a" and not self.HIDDEN_TAGS.intersection(self.context):
            self.finish_anchor()
            self.href = attributes.get("href")
        elif tag == "img" and self.href and (attributes.get("src") or attributes.get("alt")):
            self.visible = True
        if tag in self.LITERAL_TAGS:
            self.context.append(tag)

    def handle_endtag(self, tag: str) -> None:
        """Close anchors and their literal context without interpreting comments as markup."""
        if tag == "a":
            self.finish_anchor()
        if tag in self.context:
            index = len(self.context) - 1 - self.context[::-1].index(tag)
            del self.context[index:]

    def handle_data(self, data: str) -> None:
        """Visible anchor labels may contain inline formatting or code."""
        if self.href and visible_text(data) and not self.HIDDEN_TAGS.intersection(self.context):
            self.visible = True

    def close(self) -> None:
        """Account for the browser closing a final anchor at the end of the document."""
        super().close()
        self.finish_anchor()


def inline_bare_link_targets(children: list[Token], html: HTMLSourceLinks) -> Iterator[str]:
    """Exclude existing links, literal HTML contexts, images, and inline code."""
    in_link = False
    for child in children:
        if child.type == "link_open":
            in_link = True
        elif child.type == "link_close":
            in_link = False
        elif child.type == "html_inline":
            html.feed(child.content)
        elif child.type == "text" and not in_link and not html.context:
            for match in re.finditer(r"https?://github\.com/[^\s<>)\"']+", child.content):
                yield match[0].rstrip(".,;:!?")


def bare_link_targets(tokens: list[Token]) -> Iterator[str]:
    """Recognize GitHub-style bare URLs only in ordinary, unlinked Markdown text."""
    html = HTMLSourceLinks()
    for token in tokens:
        if token.type == "inline":
            yield from inline_bare_link_targets(token.children or [], html)
        elif token.type == "html_block":
            html.feed(token.content)


def rendered_link_targets(links: str) -> Iterator[str]:
    """Use CommonMark's rendered anchors and source text tokens to identify clickable links."""
    markdown = markdown_parser()
    tokens = markdown.parse(links)
    html = HTMLSourceLinks()
    html.feed(markdown.renderer.render(tokens, markdown.options, {}))
    html.close()
    yield from html.targets
    yield from bare_link_targets(tokens)


def github_link_parts(target_url: str) -> list[str]:
    """Recognize GitHub's HTTPS origin without credentials or nonstandard ports."""
    try:
        url = urlsplit(target_url)
        port = url.port
    except ValueError:
        return []
    if (
        url.scheme != "https"
        or url.hostname != "github.com"
        or url.username is not None
        or url.password is not None
        or port not in {None, 443}
    ):
        return []
    return unquote(url.path).strip("/").split("/")


def validate_versioned_links(path: Path, links: str, repo: str, *, expected_tag: str | None = None) -> None:
    """Require a tagged source root and keep final versioned links on the note's tag."""
    expected_tag = path.stem if expected_tag is None else expected_tag
    source_found = False
    for target_url in rendered_link_targets(links):
        parts = github_link_parts(target_url)
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
    command = ["gh", "api", "--method", "PATCH" if payload is not None else "GET", endpoint, "--hostname", "github.com"]
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
