"""Keep generated search content separate from documentation output paths."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

mkdocs_config = pytest.importorskip("mkdocs.config.defaults")
docs_hooks = pytest.importorskip("scripts.docs_hooks")


def test_search_index_content_does_not_select_output_paths(tmp_path: Path) -> None:
    """Location strings remain JSON data even when they resemble filesystem paths."""
    site_dir = tmp_path / "site"
    search_file = site_dir / "search" / "search_index.json"
    search_file.parent.mkdir(parents=True)
    outside_file = tmp_path / "outside.json"
    outside_file.write_text("preserve this file", encoding="utf-8")
    english = [
        {"location": "../../outside.json", "title": "Relative location", "text": "<script>& content"},
        {"location": str(outside_file), "title": "Absolute location", "text": "中文 in English index"},
    ]
    chinese = [{"location": "../../outside.json", "title": "中文标题", "text": "<script>& 中文内容"}]
    metadata = {"config": {"lang": ["en", "zh"]}, "extra": {"destination": str(outside_file)}}
    combined = {
        **metadata,
        "docs": [*english, {**chinese[0], "location": "zh-CN/../../outside.json"}],
    }
    search_file.write_text(json.dumps(combined, ensure_ascii=False), encoding="utf-8")
    config = mkdocs_config.MkDocsConfig()
    config.site_dir = str(site_dir)

    docs_hooks.on_post_build(config)

    english_text = search_file.read_text(encoding="utf-8")
    chinese_text = (site_dir / "zh-CN" / "search" / "search_index.json").read_text(encoding="utf-8")
    assert json.loads(english_text) == {**metadata, "docs": english}
    assert json.loads(chinese_text) == {**metadata, "docs": chinese}
    assert "中文 in English index" in english_text
    assert "中文标题" in chinese_text
    assert outside_file.read_text(encoding="utf-8") == "preserve this file"
    assert sorted(path.relative_to(site_dir).as_posix() for path in site_dir.rglob("*") if path.is_file()) == [
        "architecture.zh-CN/index.html",
        "gemma4-integration.zh-CN/index.html",
        "migration.zh-CN/index.html",
        "search/search_index.json",
        "zh-CN/search/search_index.json",
    ]
