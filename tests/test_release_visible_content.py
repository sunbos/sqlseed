"""Require visible subsection content without discarding literal code or images."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from scripts import sync_release_notes as sync
from tests.test_sync_release_notes import BODY

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "content",
    [
        "<!-- intentionally blank -->",
        "<!--\nHidden words\n-->",
        "<span></span>",
        "<span> \t </span>",
        '<span title="Hidden words"></span>',
        "<div>\n<span></span>\n</div>",
        "<!-- Hidden --> <span></span>",
        "- <!-- Hidden -->",
        "> <!-- Hidden -->",
        "<span>&nbsp;</span>",
        "&nbsp;",
        "&#x200b;",
        "<br>",
    ],
)
def test_invisible_subsection_content_is_rejected(tmp_path: Path, content: str) -> None:
    """Comments, empty elements, and whitespace entities do not fill a release subsection."""
    path = tmp_path / "v0.2.6.md"
    path.write_text(BODY.replace("- Preserve release assets.", content), encoding="utf-8", newline="\n")
    with pytest.raises(sync.SyncError, match="visible content"):
        sync.validate_notes(path)


@pytest.mark.parametrize(
    "content",
    [
        "<!-- Hidden --> Visible release details.",
        "<span>Visible release details.</span>",
        "<div>\nVisible release details.\n</div>",
        "```html\n<!-- A literal code example -->\n```",
        "    <!-- A literal code example -->",
        "> ```html\n> <span></span>\n> ```",
        "-     <span></span>",
        "`<!-- A literal code example -->`",
        "``<span></span>``",
        r"\<span>\</span>",
        "&lt;span&gt;&lt;/span&gt;",
        "&amp;",
        "![Release diagram](https://example.com/diagram.png)",
        '<img src="https://example.com/diagram.png" alt="Release diagram">',
        "<hr>",
    ],
)
def test_visible_subsection_examples_remain_valid(tmp_path: Path, content: str) -> None:
    """Rendered prose, literal examples, nonwhitespace entities, and images stay valid."""
    path = tmp_path / "v0.2.6.md"
    body = BODY.replace("- Preserve release assets.", content)
    path.write_text(body, encoding="utf-8", newline="\n")
    assert sync.validate_notes(path) == body
