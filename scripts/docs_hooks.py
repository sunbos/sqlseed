"""Keep localized search results and the previously published Chinese URLs."""

from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path
from typing import TYPE_CHECKING

from mkdocs.plugins import event_priority

if TYPE_CHECKING:
    from collections.abc import Iterator

    from mkdocs.config.defaults import MkDocsConfig
    from mkdocs.structure.pages import Page

_CONFIG_SCRIPT = re.compile(r'(<script id="__config"[^>]*>)(.*?)(</script>)', re.DOTALL)
_HEAD_LANGUAGE_LINK = re.compile(r'<link rel="alternate" href="[^"]+" hreflang="(?:en|zh-CN)">')
_CHINESE_PREFIX = "zh-CN/"
_LEGACY_PAGES = ("architecture", "migration", "gemma4-integration")


def _nav_pages(items: list[dict[str, object]]) -> Iterator[str]:
    for item in items:
        for value in item.values():
            if isinstance(value, list):
                yield from _nav_pages(value)
            elif isinstance(value, str) and value.endswith(".md"):
                yield value


@event_priority(-150)
def on_config(config: MkDocsConfig) -> None:
    """Allow asset fallback without silently publishing untranslated pages."""
    for filename in _nav_pages(config.nav):
        source = Path(config.docs_dir) / filename
        for page in (source, source.with_suffix(".zh-CN.md")):
            if not page.is_file():
                raise ValueError(f"Missing documentation translation: {page.name}")
    config.mdx_configs["toc"]["permalink_title"] = (
        "本节链接" if config.theme["language"] == "zh" else "Link to this section"
    )


def on_post_page(output: str, *, page: Page, **_context: object) -> str:
    """Use i18n's page links and point search at the current language's index."""
    # Material 9.7 treats head alternates as site roots and fetches a sitemap
    # below each page URL. i18n already renders working, page-specific switcher
    # links; its XML sitemap preserves hreflang metadata for search engines.
    output = _HEAD_LANGUAGE_LINK.sub("", output)
    if not page.url.startswith(_CHINESE_PREFIX):
        return output
    if (match := _CONFIG_SCRIPT.search(output)) is None:
        raise ValueError("Material's search configuration was not rendered")
    settings = json.loads(match[2])
    page_dir = posixpath.dirname(page.url)
    settings["base"] = posixpath.relpath(_CHINESE_PREFIX, page_dir)
    # Preserve Jinja's HTML-safe JSON escaping inside the script element.
    payload = json.dumps(settings).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return output[: match.start(2)] + payload + output[match.end(2) :]


@event_priority(-200)
def on_post_build(config: MkDocsConfig) -> None:
    """Run after i18n has assembled the combined search index."""
    site_dir = Path(config.site_dir)
    search_file = site_dir / "search" / "search_index.json"
    index = json.loads(search_file.read_text(encoding="utf-8"))
    english = []
    chinese = []
    for entry in index["docs"]:
        if entry["location"].startswith(_CHINESE_PREFIX):
            chinese.append({**entry, "location": entry["location"][len(_CHINESE_PREFIX) :]})
        else:
            english.append(entry)
    chinese_file = site_dir / _CHINESE_PREFIX / "search" / "search_index.json"
    chinese_file.parent.mkdir(parents=True, exist_ok=True)
    chinese_file.write_text(json.dumps({**index, "docs": chinese}, ensure_ascii=False), encoding="utf-8")
    search_file.write_text(json.dumps({**index, "docs": english}, ensure_ascii=False), encoding="utf-8")

    for name in _LEGACY_PAGES:
        target = f"../zh-CN/{name}/"
        destination = site_dir / f"{name}.zh-CN" / "index.html"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<meta http-equiv="refresh" content="0; url={target}">'
            "<title>文档已迁移 · sqlseed</title></head><body>"
            f'<p><a href="{target}">前往中文版文档</a></p>'
            f'<script>location.replace("{target}" + location.search + location.hash);</script>'
            "</body></html>\n",
            encoding="utf-8",
        )
