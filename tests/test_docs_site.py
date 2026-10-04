"""Exercise the published bilingual documentation as real built HTML."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import pytest

pytest.importorskip("mkdocs")

ROOT = Path(__file__).resolve().parents[1]
SITE_URL = "https://sunbos.github.io/sqlseed/"
TOPICS = (
    "",
    "guide/",
    "web-workbench/",
    "migration/",
    "maintainable-release/",
    "api/",
    "architecture/",
    "gemma4-integration/",
    "releasing/",
    "development/web-i18n/",
    "project-showcase/",
)
LANGUAGES = ("en", "zh-CN")
NAV_LABELS = {
    "en": ("Home", "User Guide", "Reference", "Maintenance"),
    "zh-CN": ("首页", "使用指南", "参考文档", "维护开发"),
}


@dataclass
class Link:
    """One rendered link and the navigation context in which it appears."""

    href: str
    text: str = ""
    language: str | None = None
    top_navigation: bool = False


class Document(HTMLParser):
    """Read semantic navigation, anchors, and Material's client configuration."""

    def __init__(self, html: str) -> None:
        super().__init__()
        self.language = ""
        self.ids: set[str] = set()
        self.links: list[Link] = []
        self.resources: list[str] = []
        self.language_roots: list[str] = []
        self.headings: list[str] = []
        self.refresh = ""
        self.config_text = ""
        self._navigation: list[bool] = []
        self._link: Link | None = None
        self._in_heading = False
        self._in_config = False
        self.feed(html)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if identifier := attributes.get("id"):
            self.ids.add(identifier)
        if tag == "html":
            self.language = attributes.get("lang") or ""
        elif tag == "nav":
            self._navigation.append("md-tabs" in (attributes.get("class") or "").split())
        elif tag == "a" and attributes.get("href") is not None:
            self._link = Link(
                href=attributes.get("href") or "",
                language=attributes.get("hreflang"),
                top_navigation=any(self._navigation),
            )
            self.links.append(self._link)
        elif tag in {"img", "script", "link"}:
            resource = attributes.get("href" if tag == "link" else "src")
            if resource:
                self.resources.append(resource)
                if tag == "link" and attributes.get("rel") == "alternate" and attributes.get("hreflang"):
                    self.language_roots.append(resource)
        if tag == "h1":
            self._in_heading = True
            self.headings.append("")
        elif tag == "script" and attributes.get("id") == "__config":
            self._in_config = True
        elif tag == "meta" and attributes.get("http-equiv", "").lower() == "refresh":
            self.refresh = attributes.get("content") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._link = None
        elif tag == "nav":
            self._navigation.pop()
        elif tag == "h1":
            self._in_heading = False
        elif tag == "script":
            self._in_config = False

    def handle_data(self, data: str) -> None:
        if self._link is not None:
            self._link.text += data
        if self._in_heading:
            self.headings[-1] += data
        if self._in_config:
            self.config_text += data


def _page_path(language: str, topic: str) -> str:
    """Return the public page URL relative to the deployment root."""
    return ("zh-CN/" if language == "zh-CN" else "") + topic


def _document(site: Path, page: str) -> Document:
    """Parse one page from a real build output."""
    return Document((site / page / "index.html").read_text(encoding="utf-8"))


def _internal_target(page: str, href: str) -> tuple[str, str] | None:
    """Resolve a browser URL, leaving external services outside this test."""
    target = urlsplit(urljoin(SITE_URL + page, href))
    if target.scheme != "https" or target.netloc != "sunbos.github.io":
        return None
    if not target.path.startswith("/sqlseed/"):
        return None
    return unquote(target.path.removeprefix("/sqlseed/")), unquote(target.fragment)


def _build(site: Path, config: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the installed MkDocs CLI without network services or mocks."""
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "mkdocs",
            "build",
            "--strict",
            "--config-file",
            str(config),
            "--site-dir",
            str(site),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONUTF8": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


@pytest.fixture(scope="module")
def docs_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build once so all assertions observe the same deployable artifact."""
    site = tmp_path_factory.mktemp("docs-site")
    result = _build(site, ROOT / "mkdocs.yml")
    assert result.returncode == 0, result.stdout + result.stderr
    return site


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("topic", TOPICS, ids=lambda topic: topic or "home")
def test_pages_keep_language_navigation_and_topic_when_switching(docs_site: Path, language: str, topic: str) -> None:
    """Every topic has genuine localized content and a matching language switch."""
    page = _page_path(language, topic)
    document = _document(docs_site, page)
    assert document.language == ("zh" if language == "zh-CN" else "en")
    assert len(document.headings) == 1
    contains_chinese = re.search(r"[\u4e00-\u9fff]", document.headings[0]) is not None
    assert contains_chinese == (language == "zh-CN"), document.headings
    navigation = tuple(" ".join(link.text.split()) for link in document.links if link.top_navigation)
    assert navigation == NAV_LABELS[language]
    for other_language in LANGUAGES:
        switches = [link for link in document.links if link.language == other_language]
        assert switches, (page, other_language)
        assert all(_internal_target(page, link.href) == (_page_path(other_language, topic), "") for link in switches)
    for link in document.links:
        if link.top_navigation:
            target = _internal_target(page, link.href)
            assert target is not None
            assert target[0].startswith("zh-CN/") == (language == "zh-CN")


@pytest.mark.parametrize("language", LANGUAGES)
def test_search_results_use_only_the_current_language(docs_site: Path, language: str) -> None:
    """Search results must resolve from each locale root without doubled prefixes."""
    locale_root = _page_path(language, "")
    index = json.loads((docs_site / locale_root / "search/search_index.json").read_text("utf-8"))
    entries = index["docs"]
    assert entries
    pages = {urlsplit(entry["location"]).path for entry in entries}
    assert pages == set(TOPICS)
    documents = {_page_path(language, topic): _document(docs_site, _page_path(language, topic)) for topic in TOPICS}
    for entry in entries:
        location = entry["location"]
        assert not location.startswith(("/", "zh-CN/", "../")), location
        target = _internal_target(locale_root, location)
        assert target is not None
        path, fragment = target
        document = documents[path]
        if fragment:
            assert fragment in document.ids, location
    home = next(entry for entry in entries if entry["location"] == "")
    if language == "zh-CN":
        assert "从现有结构生成测试数据" in home["title"]
    else:
        assert "Test data, from your schema" in home["title"]
        assert all(re.search(r"[\u4e00-\u9fff]", entry["title"]) is None for entry in entries)
    for topic in TOPICS:
        page = _page_path(language, topic)
        settings = json.loads(documents[page].config_text)
        base_url = urljoin(SITE_URL + page, settings["base"].rstrip("/") + "/")
        assert base_url == SITE_URL + locale_root


def test_published_internal_links_and_assets_exist(docs_site: Path) -> None:
    """Check rendered links and anchors, including references between languages."""
    documents = {
        _page_path(language, topic): _document(docs_site, _page_path(language, topic))
        for language in LANGUAGES
        for topic in TOPICS
    }
    for page, document in documents.items():
        for href in [link.href for link in document.links] + document.resources:
            target = _internal_target(page, href)
            if target is None:
                continue
            path, fragment = target
            destination = docs_site / path
            if destination.is_dir():
                destination /= "index.html"
            assert destination.is_file(), (page, href)
            if fragment and destination.suffix == ".html":
                parsed = documents.get(path) or Document(destination.read_text(encoding="utf-8"))
                assert fragment in parsed.ids, (page, href, fragment)


def test_language_metadata_preserves_page_pairs_without_invalid_sitemap_requests(docs_site: Path) -> None:
    """Publish hreflang in the sitemap without Material probing below every page."""
    namespaces = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "x": "http://www.w3.org/1999/xhtml"}
    sitemap = ET.parse(docs_site / "sitemap.xml").getroot()
    entries = {entry.findtext("s:loc", namespaces=namespaces): entry for entry in sitemap.findall("s:url", namespaces)}
    for language in LANGUAGES:
        for topic in TOPICS:
            page = _page_path(language, topic)
            document = _document(docs_site, page)
            # These are interpreted as locale roots by Material 9.7's client.
            assert not document.language_roots, (page, document.language_roots)
            entry = entries[SITE_URL + page]
            alternatives = {
                link.attrib["hreflang"]: link.attrib["href"] for link in entry.findall("x:link", namespaces)
            }
            assert alternatives == {locale: SITE_URL + _page_path(locale, topic) for locale in LANGUAGES}


@pytest.mark.parametrize("topic", ("architecture", "migration", "gemma4-integration"))
def test_preexisting_chinese_urls_have_a_working_destination(docs_site: Path, topic: str) -> None:
    """Old indexed URLs remain usable with an HTML link and an automatic redirect."""
    page = f"{topic}.zh-CN/"
    document = _document(docs_site, page)
    assert document.language in {"zh", "zh-CN"}
    expected = (f"zh-CN/{topic}/", "")
    assert any(_internal_target(page, link.href) == expected for link in document.links)
    refresh_target = document.refresh.partition("url=")[2]
    assert refresh_target
    assert _internal_target(page, refresh_target) == expected
    assert (docs_site / expected[0] / "index.html").is_file()


def test_missing_translation_fails_instead_of_silently_publishing_english(tmp_path: Path) -> None:
    """Shared images may fall back, but a missing translated article must fail."""
    source = tmp_path / "docs"
    for topic in TOPICS:
        stem = topic.rstrip("/") or "index"
        for language in LANGUAGES:
            suffix = ".zh-CN.md" if language == "zh-CN" else ".md"
            relative = Path(stem + suffix)
            if relative == Path("guide.zh-CN.md"):
                continue
            destination = source / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "docs" / relative, destination)
    config = tmp_path / "mkdocs.yml"
    config.write_text(
        f"INHERIT: {json.dumps(str(ROOT / 'mkdocs.yml'))}\n"
        f"docs_dir: {json.dumps(str(source))}\n"
        f"hooks:\n  - {json.dumps(str(ROOT / 'scripts/docs_hooks.py'))}\n",
        encoding="utf-8",
    )
    result = _build(tmp_path / "site", config)
    assert result.returncode != 0
    assert "guide.zh-CN.md" in result.stdout + result.stderr
