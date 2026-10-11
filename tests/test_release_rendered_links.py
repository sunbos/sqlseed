"""Require a clickable source reference instead of a URL hidden in examples."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from scripts import sync_release_notes as sync

if TYPE_CHECKING:
    from pathlib import Path

SOURCE = "https://github.com/sunbos/sqlseed/tree/v0.2.6"
BODY = """## English

### Fixed

- Preserve release metadata.

## 中文

### 修复

- 保留发布元数据。

## Links / 相关链接

Source references and examples:

"""


@pytest.mark.parametrize(
    "links",
    [
        f"```markdown\n[Source]({SOURCE})\n```",
        f"~~~\n{SOURCE}\n~~~",
        f"- Example:\n\n  ```text\n  {SOURCE}\n  ```",
        f"> ```\n> {SOURCE}\n> ```",
        f"    [Source]({SOURCE})",
        f"`{SOURCE}`",
        f"``[Source]({SOURCE})``",
        f"<!-- [Source]({SOURCE}) -->",
        f"<!--\nSource: {SOURCE}\n-->",
        f'<span data-source="{SOURCE}">Source</span>',
        f'<img src="{SOURCE}" alt="Source">',
        f"![Source]({SOURCE})",
        f"![{SOURCE}](https://example.com/image.png)",
        f"![Source][source]\n\n[source]: {SOURCE}",
        f"[source]: {SOURCE}",
        f"<code>{SOURCE}</code>",
        f"<code>\n\n{SOURCE}\n\n</code>",
        f"<pre>\n{SOURCE}\n</pre>",
        f"<div>\n{SOURCE}\n</div>",
        f"[{SOURCE}](https://example.com/other)",
        f'<a href="https://example.com/other">{SOURCE}</a>',
        f'<a href="{SOURCE}"></a>',
    ],
    ids=[
        "fenced-markdown",
        "fenced-url",
        "list-fence",
        "quote-fence",
        "indented-code",
        "inline-code",
        "inline-code-link",
        "html-comment",
        "multiline-comment",
        "html-attribute",
        "html-image",
        "markdown-image",
        "image-alt",
        "reference-image",
        "unused-reference",
        "html-code",
        "html-code-paragraph",
        "html-pre",
        "html-raw-text",
        "other-link-label",
        "other-anchor-label",
        "empty-anchor",
    ],
)
def test_hidden_or_non_link_source_url_is_rejected(tmp_path: Path, links: str) -> None:
    """Readable prose keeps this failure specific to the absence of a source hyperlink."""
    path = tmp_path / "v0.2.6.md"
    path.write_text(BODY + links + "\n", encoding="utf-8", newline="\n")
    with pytest.raises(sync.SyncError, match="must include a source link"):
        sync.validate_notes(path)


@pytest.mark.parametrize(
    "links",
    [
        f"[Source]({SOURCE})",
        f"[`Source`]({SOURCE})",
        f"[Source [snapshot]]({SOURCE})",
        f'[Source](<{SOURCE}> "Tagged snapshot")',
        f"<{SOURCE}>",
        SOURCE,
        f"- [Source]({SOURCE})",
        f"> [Source]({SOURCE})",
        f"[Source][snapshot]\n\n[snapshot]: {SOURCE}",
        f"[Source][]\n\n[source]: {SOURCE}",
        f"[Source]\n\n[source]: {SOURCE}",
        f"[![Source](https://example.com/image.png)]({SOURCE})",
        f'<a href="{SOURCE}">Source</a>',
        f'<div>\n<a href="{SOURCE}">Source</a>\n</div>',
        f'<a href="{SOURCE}"><code>Source</code></a>',
    ],
    ids=[
        "markdown-inline",
        "code-label",
        "nested-label",
        "titled-link",
        "autolink",
        "gfm-bare-url",
        "list-link",
        "quoted-link",
        "reference-link",
        "collapsed-reference",
        "shortcut-reference",
        "linked-image",
        "html-anchor",
        "html-block-anchor",
        "html-code-label",
    ],
)
def test_rendered_source_link_forms_remain_valid(tmp_path: Path, links: str) -> None:
    """Legitimate direct, referenced, automatic, and HTML links remain usable."""
    path = tmp_path / "v0.2.6.md"
    body = BODY + links + "\n"
    path.write_text(body, encoding="utf-8", newline="\n")
    assert sync.validate_notes(path) == body


@pytest.mark.parametrize(
    "example",
    [
        "`https://github.com/sunbos/sqlseed/tree/v0.2.5`",
        "<!-- https://github.com/sunbos/sqlseed/tree/v0.2.5 -->",
        "```\nhttps://github.com/sunbos/sqlseed/tree/v0.2.5\n```",
    ],
)
def test_non_link_historical_examples_do_not_override_valid_source(tmp_path: Path, example: str) -> None:
    """Only rendered links enforce link targets, so literal historical examples remain text."""
    path = tmp_path / "v0.2.6.md"
    body = BODY + f"[Source]({SOURCE})\n\n{example}\n"
    path.write_text(body, encoding="utf-8", newline="\n")
    assert sync.validate_notes(path) == body
