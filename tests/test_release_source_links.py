"""Require release notes to link the source snapshot of their own version."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from scripts import sync_release_notes as sync

if TYPE_CHECKING:
    from pathlib import Path

BODY = """## English

### Fixed

- Validate release metadata.

## 中文

### 修复

- 校验发布元数据。

## Links / 相关链接

"""


@pytest.mark.parametrize(
    "links",
    [
        "- No links yet.",
        "- [Repository](https://github.com/sunbos/sqlseed)",
        "- [Source](https://github.com/other/project/tree/v0.2.6)",
        "- [Changes](https://github.com/sunbos/sqlseed/compare/v0.2.5...v0.2.6)",
        "- [Changelog](https://github.com/sunbos/sqlseed/blob/v0.2.6/CHANGELOG.md)",
        "- [Module](https://github.com/sunbos/sqlseed/tree/v0.2.6/src)",
    ],
)
def test_notes_require_their_own_tagged_source_link(tmp_path: Path, links: str) -> None:
    """Other useful links cannot substitute for the release's source snapshot."""
    path = tmp_path / "v0.2.6.md"
    path.write_text(BODY + links + "\n", encoding="utf-8")
    with pytest.raises(sync.SyncError, match="must include a source link"):
        sync.validate_notes(path)


@pytest.mark.parametrize("repo", ["sunbos/sqlseed", "owner/fork"])
@pytest.mark.parametrize("suffix", ["", "/", "#readme"])
def test_tagged_source_link_follows_selected_repository(tmp_path: Path, repo: str, suffix: str) -> None:
    """The selected repository's exact-tag source root satisfies the link contract."""
    path = tmp_path / "v0.2.6.md"
    body = BODY + f"- [Source](https://github.com/{repo}/tree/v0.2.6{suffix})\n"
    path.write_text(body, encoding="utf-8")
    assert sync.validate_notes(path, repo) == body


def test_source_reference_in_prose_does_not_replace_links_section(tmp_path: Path) -> None:
    """A source URL mentioned in a historical explanation is not the final source link."""
    path = tmp_path / "v0.2.6.md"
    body = BODY.replace(
        "- Validate release metadata.", "- Previously used https://github.com/sunbos/sqlseed/tree/v0.2.6."
    )
    path.write_text(body + "- No links yet.\n", encoding="utf-8")
    with pytest.raises(sync.SyncError, match="must include a source link"):
        sync.validate_notes(path)
