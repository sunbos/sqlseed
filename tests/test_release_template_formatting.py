"""Keep template prose detectable when presentation markup changes its source text."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from scripts import sync_release_notes as sync
from tests.test_sync_release_notes import BODY

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("instruction", ["Describe a user-visible addition.", "描述用户可见的新增能力。"])
@pytest.mark.parametrize(
    "presentation",
    [
        "**{text}**",
        "*{text}*",
        "[{text}](https://example.com/template)",
        "**[{text}](https://example.com/template)**",
        "<span>{text}</span>",
        "<em>{text}</em>",
        "<strong>{text}</strong>",
        '<a href="https://example.com/template">{text}</a>',
    ],
)
def test_formatted_template_instruction_is_rejected(tmp_path: Path, instruction: str, presentation: str) -> None:
    """Formatting and link destinations do not turn a copied instruction into release content."""
    path = tmp_path / "v0.2.6.md"
    body = BODY.replace("- Preserve release assets.", "- " + presentation.format(text=instruction))
    path.write_text(body, encoding="utf-8", newline="\n")
    with pytest.raises(sync.SyncError, match="template instructions"):
        sync.validate_notes(path)


@pytest.mark.parametrize(
    "example",
    [
        "> - **Describe a user-visible addition.**",
        "> - <span>Describe a user-visible addition.</span>",
        "- **`Describe a user-visible addition.`**",
        "- [`Describe a user-visible addition.`](https://example.com/template)",
        "- <code>Describe a user-visible addition.</code>",
        "- <q>Describe a user-visible addition.</q>",
        "<blockquote>Describe a user-visible addition.</blockquote>",
        "<pre>Describe a user-visible addition.</pre>",
        "<div><code>Describe a user-visible addition.</code></div>",
        "- Fixed **Describe a user-visible addition.** copied into the previous notes.",
    ],
)
def test_formatted_instruction_examples_remain_valid(tmp_path: Path, example: str) -> None:
    """Code, quotations, and surrounding explanatory prose remain legitimate examples."""
    path = tmp_path / "v0.2.6.md"
    body = BODY.replace("- Preserve release assets.", example)
    path.write_text(body, encoding="utf-8", newline="\n")
    assert sync.validate_notes(path) == body


@pytest.mark.parametrize(
    "example",
    [
        "<div>Describe a user-visible addition.</div>",
        "<span>\nDescribe a user-visible addition.\n</span>",
    ],
)
def test_html_block_template_instruction_is_rejected(tmp_path: Path, example: str) -> None:
    """Raw HTML blocks must not bypass the same rendered-prose rule as inline wrappers."""
    path = tmp_path / "v0.2.6.md"
    body = BODY.replace("- Preserve release assets.", example)
    path.write_text(body, encoding="utf-8", newline="\n")
    with pytest.raises(sync.SyncError, match="template instructions"):
        sync.validate_notes(path)
