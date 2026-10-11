"""Distinguish extra headings from separators and Markdown examples."""

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
        "<https://example.com>\n---",
        "<em>Unexpected</em>\n---",
    ],
)
def test_extra_setext_heading_is_rejected(tmp_path: Path, content: str) -> None:
    """A paragraph followed by a Setext underline creates a forbidden extra section."""
    path = tmp_path / "v0.2.6.md"
    path.write_text(BODY.replace("- Preserve release assets.", content), encoding="utf-8", newline="\n")
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
        "<div>Text</div>\n---",
        "<span>\n---",
        "---\n- Preserve release assets.",
    ],
)
def test_separators_and_code_examples_remain_valid(tmp_path: Path, content: str) -> None:
    """Lists, quotations, code, and paragraph breaks can be followed by a thematic break."""
    path = tmp_path / "v0.2.6.md"
    body = BODY.replace("- Preserve release assets.", content)
    path.write_text(body, encoding="utf-8", newline="\n")
    assert sync.validate_notes(path) == body


@pytest.mark.parametrize(
    "content",
    [
        *(f"<h{level}>Unexpected</h{level}>" for level in range(1, 7)),
        '<H2 id="extra">Unexpected</H2>',
        "<h3\n class='extra'\n>Other</h3>",
        "<h2/>",
        "Text <h2>Unexpected</h2>",
        "`Unclosed <h2>Unexpected</h2>",
        "``Mismatched <h2>Unexpected</h2>`",
        r"\`<h2>Unexpected</h2>`",
        r"\\<h2>Unexpected</h2>",
        "Text\n    <h2>Unexpected</h2>",
        "<div>\n<h2>Unexpected</h2>\n</div>",
        "`one\n<h2>Unexpected</h2>\n`",
        "`<h2>Example</h2>` and <h3>Other</h3>",
        "```html\n<h2>Example</h2>\n```\n<h3>Other</h3>",
        '<h2 title="`">Unexpected</h2> trailing `',
        "`<!--` followed by <h2>Unexpected</h2>",
        "<div>\n`<h2>Unexpected</h2>`\n</div>",
        "<div>`<h2>Unexpected</h2>`</div>",
        "<div>\n\\<h2>Unexpected</h2>\n</div>",
        "<div>\n```\n<h2>Unexpected</h2>\n```\n</div>",
    ],
)
def test_raw_html_heading_is_rejected(tmp_path: Path, content: str) -> None:
    """HTML section tags cannot bypass the canonical Markdown heading structure."""
    path = tmp_path / "v0.2.6.md"
    path.write_text(BODY.replace("- Preserve release assets.", content), encoding="utf-8", newline="\n")
    with pytest.raises(sync.SyncError, match="HTML headings"):
        sync.validate_notes(path)


@pytest.mark.parametrize(
    "content",
    [
        "```html\n<h2>Example</h2>\n```",
        "~~~html\n<H3>Example</H3>\n~~~",
        "    <h2>Example</h2>",
        "\t<h2>Example</h2>",
        "`<h2>Example</h2>`",
        "``<h3>Example ` value</h3>``",
        "Example: ```<h2>Example `` value</h2>```",
        "`one\ntext <h2>Example</h2>\n`",
        "`<h2>Example</h2>\\`",
        r"\\`<h2>Example</h2>`",
        r"\``<h2>Example</h2>`",
        r"\<h2>Example\</h2>",
        r"\\\<h2>Example</h2>",
        "&lt;h2&gt;Example&lt;/h2&gt;",
        "&#60;h2&#62;Example&#60;/h2&#62;",
        "<!-- <h2>Example</h2> -->\n\nVisible release details.",
        "<!--\n<h2>Example</h2>\n-->\n\nVisible release details.",
        '<span title="<h2>Example</h2>">Text</span>',
        '<span title="`<h2>Example</h2>`">Text</span>',
        "<h20>Text</h20>",
        "<div>\n\n`<h2>Example</h2>`\n\n</div>",
        "```html\n<div>\n<h2>Example</h2>\n</div>\n```",
    ],
)
def test_html_heading_examples_remain_valid(tmp_path: Path, content: str) -> None:
    """Code, escaping, comments, and attributes do not create rendered headings."""
    path = tmp_path / "v0.2.6.md"
    body = BODY.replace("- Preserve release assets.", content)
    path.write_text(body, encoding="utf-8", newline="\n")
    assert sync.validate_notes(path) == body


@pytest.mark.parametrize(
    "content",
    [
        "> ## Unexpected",
        "- ## Unexpected",
        "+ ### Unexpected",
        "* # Unexpected",
        "1. #### Unexpected",
        "1) ##### Unexpected",
        "> - ## Unexpected",
        "- > ## Unexpected",
        "> > ###### Unexpected",
        "- Item\n\n  ## Unexpected",
        "10. Item\n\n    ## Unexpected",
        "> Unexpected\n> ---",
        "- Unexpected\n  ---",
        "> ```\n> Example\n## Unexpected",
        "- ```\n  Example\n- ## Unexpected",
    ],
)
def test_container_heading_is_rejected(tmp_path: Path, content: str) -> None:
    """Quotes and list items cannot add rendered sections or hide them behind code fences."""
    path = tmp_path / "v0.2.6.md"
    path.write_text(BODY.replace("- Preserve release assets.", content), encoding="utf-8", newline="\n")
    with pytest.raises(sync.SyncError, match="heading"):
        sync.validate_notes(path)


@pytest.mark.parametrize(
    "content",
    [
        "> ```markdown\n> ## Example\n> ```",
        "- ```markdown\n  ## Example\n  ```",
        "10. ```markdown\n    ## Example\n    ```",
        "> - ```html\n>   <h2>Example</h2>\n>   ```",
        "- > ```markdown\n  > ## Example\n  > ```",
        ">     ## Example",
        "-     ## Example",
        "- Item\n\n      ## Example",
        ">     <h2>Example</h2>",
        "- Item\n\n      <h2>Example</h2>",
        "> `## Example`",
        "- `## Example`",
        "~~~bad`info\n## Example\n~~~",
        "```some `inline code```",
        "- Item\n> ---",
        "Text\n> ---",
    ],
)
def test_container_code_and_fence_examples_remain_valid(tmp_path: Path, content: str) -> None:
    """Relative code indentation, nested fences, and valid info strings remain usable."""
    path = tmp_path / "v0.2.6.md"
    body = BODY.replace("- Preserve release assets.", content)
    path.write_text(body, encoding="utf-8", newline="\n")
    assert sync.validate_notes(path) == body


@pytest.mark.parametrize("opening", ["```bad`info", "````bad``info", "> ```bad`info", "- ```bad`info"])
def test_invalid_backtick_info_cannot_hide_headings(tmp_path: Path, opening: str) -> None:
    """A backtick in an opening info string must not put following headings in code."""
    path = tmp_path / "v0.2.6.md"
    body = BODY.replace("- Preserve release assets.", f"{opening}\n## Unexpected\n````")
    path.write_text(body, encoding="utf-8", newline="\n")
    with pytest.raises(sync.SyncError, match=r"heading|fenced"):
        sync.validate_notes(path)
