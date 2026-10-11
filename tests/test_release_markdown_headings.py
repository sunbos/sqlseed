"""Distinguish extra Setext sections from separators and Markdown examples."""

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
        "Unexpected\n---",
        "Unexpected\n===",
        "Unexpected\n-",
        "Unexpected\n=",
        "Unexpected\ncontinuation\n   -- \t",
        "***\nUnexpected\n---",
        "Unexpected\n    continuation\n---",
        "Unexpected\n\tcontinuation\n---",
        "Unexpected\n    ---\n---",
        "    Code example\nUnexpected\n---",
    ],
)
def test_extra_setext_heading_is_rejected(tmp_path: Path, content: str) -> None:
    """A paragraph followed by a Setext underline creates a forbidden extra section."""
    path = tmp_path / "v0.2.6.md"
    path.write_text(BODY.replace("- Preserve release assets.", content), encoding="utf-8")
    with pytest.raises(sync.SyncError, match="Setext"):
        sync.validate_notes(path)


@pytest.mark.parametrize(
    "content",
    [
        "Preserve release assets.\n\n---",
        "- Preserve release assets.\n---",
        "- Preserve release assets.\n  continuation\n---",
        "- Preserve release assets.\ncontinuation\n---",
        "> Preserve release assets.\n---",
        "> Preserve release assets.\ncontinuation\n---",
        "```markdown\nUnexpected\n---\n```\n---",
        "~~~markdown\nUnexpected\n===\n~~~\n---",
        "    Unexpected\n    ---\n---",
        "\tUnexpected\n\t---\n---",
        "Unexpected\n    ---",
        "[reference]: https://example.com\n---",
        "<!-- comment -->\n---",
        "---\n- Preserve release assets.",
    ],
)
def test_separators_and_code_examples_remain_valid(tmp_path: Path, content: str) -> None:
    """Lists, quotations, code, and paragraph breaks can be followed by a thematic break."""
    path = tmp_path / "v0.2.6.md"
    body = BODY.replace("- Preserve release assets.", content)
    path.write_text(body, encoding="utf-8")
    assert sync.validate_notes(path) == body
