from __future__ import annotations

import hashlib
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote
from xml.etree import ElementTree

import ebooklib
from ebooklib import epub

from .models import ChapterInfo, ImageInfo, QualityIssue


@dataclass
class EpubInspection:
    path: Path
    title: str
    author: str
    opf_identifier: str
    chapters: list[ChapterInfo] = field(default_factory=list)
    images: list[ImageInfo] = field(default_factory=list)
    issues: list[QualityIssue] = field(default_factory=list)
    missing_cover: bool = True


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return ""
    if isinstance(value, (tuple, list)):
        for part in value:
            extracted = _string_value(part)
            if extracted:
                return extracted
        return ""
    return str(value).strip()


def _metadata_first(book: epub.EpubBook, namespace: str, name: str, default: str = "") -> str:
    for value in book.get_metadata(namespace, name):
        extracted = _string_value(value)
        if extracted:
            return extracted
    return default


class _ReaderBodyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._body_depth = 0
        self._ignored_depth = 0
        self._texts: list[str] = []
        self._structure: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._enter_tag(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"head", "h1", "h2", "h3", "h4", "h5", "h6"}:
            return
        if self._body_depth and not self._ignored_depth:
            self._structure.append(f"<{self._structure_tag(tag, attrs)}/>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"head", "h1", "h2", "h3", "h4", "h5", "h6"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._body_depth and not self._ignored_depth and tag != "body":
            self._structure.append(f"</{tag}>")
        if tag == "body" and self._body_depth:
            self._body_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._body_depth and not self._ignored_depth:
            self._texts.append(data)
            text = _normalise_text(data)
            if text:
                self._structure.append(f"text:{text}")

    def text(self) -> str:
        return "".join(self._texts)

    def structure(self) -> str:
        return "\n".join(self._structure)

    def _enter_tag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "body":
            self._body_depth += 1
        if tag in {"head", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._ignored_depth += 1
            return
        if self._body_depth and not self._ignored_depth and tag != "body":
            self._structure.append(f"<{self._structure_tag(tag, attrs)}>")

    def _structure_tag(self, tag: str, attrs: list[tuple[str, str | None]]) -> str:
        anchors = []
        for key, value in attrs:
            if key and key.lower() in {"id", "name"} and value:
                anchors.append(f'{key.lower()}="{value.strip()}"')
        return " ".join([tag, *anchors])


def _normalise_text(raw: str) -> str:
    return re.sub(r"\s+", "", raw)


def _reader_body_text(raw_html: bytes) -> str:
    parser = _ReaderBodyParser()
    parser.feed(raw_html.decode("utf-8", errors="replace"))
    parser.close()
    return parser.text()


def _fingerprint(raw_html: bytes) -> tuple[str, int, str]:
    parser = _ReaderBodyParser()
    parser.feed(raw_html.decode("utf-8", errors="replace"))
    parser.close()
    text = _normalise_text(parser.text())
    structure = parser.structure()
    return (
        hashlib.sha256(text.encode("utf-8")).hexdigest(),
        len(text),
        hashlib.sha256(structure.encode("utf-8")).hexdigest(),
    )


def _css_issues(item_name: str, css: str) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    if re.search(r"font-size\s*:\s*\d+(?:\.\d+)?\s*(?:px|pt)\b", css, re.IGNORECASE):
        issues.append(
            QualityIssue("HIGH", "CSS_ABSOLUTE_FONT_SIZE", "CSS uses px/pt font-size", item_name)
        )
    if re.search(r"line-height\s*:\s*0\.\d+", css, re.IGNORECASE):
        issues.append(
            QualityIssue("MEDIUM", "CSS_LOW_LINE_HEIGHT", "CSS line-height is below 1.0", item_name)
        )
    return issues


def _is_nav_document(item: epub.EpubItem) -> bool:
    name = _basename(str(getattr(item, "file_name", ""))).lower()
    if name in {"nav.xhtml", "nav.html"}:
        return True
    if _string_value(getattr(item, "id", "")).lower() == "nav":
        return True
    return "nav" in _property_tokens(item)


def _basename(href: str) -> str:
    return PurePosixPath(href.replace("\\", "/")).name


def _property_tokens(item: epub.EpubItem) -> set[str]:
    properties = getattr(item, "properties", "")
    if isinstance(properties, str):
        return {token.lower() for token in properties.split()}
    if isinstance(properties, (list, tuple, set)):
        return {_string_value(token).lower() for token in properties if _string_value(token)}
    return set()


def _cover_item_ids(book: epub.EpubBook) -> set[str]:
    cover_ids: set[str] = set()
    for _, attrs in book.get_metadata("OPF", "meta"):
        if not isinstance(attrs, dict):
            continue
        if _string_value(attrs.get("name")).lower() == "cover":
            cover_id = _string_value(attrs.get("content"))
            if cover_id:
                cover_ids.add(cover_id)
    return cover_ids


def _normalise_epub_href(href: str) -> str:
    normalised = posixpath.normpath(unquote(href).replace("\\", "/").lstrip("/"))
    return "" if normalised == "." else normalised


def _opf_relative_href(opf_path: str, href: str) -> str:
    opf_dir = posixpath.dirname(_normalise_epub_href(opf_path))
    if not opf_dir:
        return _normalise_epub_href(href)
    return _normalise_epub_href(posixpath.join(opf_dir, href))


def _epub3_cover_references(path: Path) -> tuple[set[str], set[str]]:
    cover_ids: set[str] = set()
    cover_hrefs: set[str] = set()
    container_ns = {"container": "urn:oasis:names:tc:opendocument:xmlns:container"}
    opf_ns = {"opf": "http://www.idpf.org/2007/opf"}

    try:
        with zipfile.ZipFile(path) as archive:
            container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
            rootfile = container.find(".//container:rootfile", container_ns)
            if rootfile is None:
                return cover_ids, cover_hrefs
            opf_path = _string_value(rootfile.attrib.get("full-path"))
            if not opf_path:
                return cover_ids, cover_hrefs

            opf_root = ElementTree.fromstring(archive.read(opf_path))
    except (KeyError, ElementTree.ParseError, zipfile.BadZipFile):
        return cover_ids, cover_hrefs

    for manifest_item in opf_root.findall(".//opf:manifest/opf:item", opf_ns):
        properties = {
            token.lower()
            for token in _string_value(manifest_item.attrib.get("properties")).split()
        }
        if "cover-image" not in properties:
            continue

        item_id = _string_value(manifest_item.attrib.get("id"))
        href = _string_value(manifest_item.attrib.get("href"))
        if item_id:
            cover_ids.add(item_id)
        if href:
            cover_hrefs.add(_normalise_epub_href(href))
            cover_hrefs.add(_opf_relative_href(opf_path, href))

    return cover_ids, cover_hrefs


def _is_cover_image(item: epub.EpubItem, cover_item_ids: set[str], cover_hrefs: set[str]) -> bool:
    item_id = _string_value(getattr(item, "id", ""))
    if item_id in cover_item_ids:
        return True
    href = _normalise_epub_href(str(getattr(item, "file_name", "")))
    if href in cover_hrefs:
        return True
    if "cover-image" in _property_tokens(item):
        return True
    return PurePosixPath(href).stem.lower() == "cover"


def _spine_item_id(entry: Any) -> str:
    if isinstance(entry, (tuple, list)):
        return _string_value(entry[0]) if entry else ""
    if isinstance(entry, str):
        return entry
    return _string_value(getattr(entry, "id", ""))


def _chapter_info(index: int, item: epub.EpubItem, item_id: str) -> ChapterInfo:
    href = str(getattr(item, "file_name", ""))
    fingerprint, text_chars, structure_fingerprint = _fingerprint(item.get_content())
    title = _string_value(getattr(item, "title", "")) or href
    return ChapterInfo(index, title, href, fingerprint, text_chars, item_id, structure_fingerprint)


def _spine_ordered_document_items(book: epub.EpubBook) -> list[tuple[epub.EpubItem, str]]:
    documents = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
    documents_by_id = {
        _string_value(getattr(item, "id", "")): item
        for item in documents
        if _string_value(getattr(item, "id", ""))
    }

    ordered: list[tuple[epub.EpubItem, str]] = []
    seen: set[str] = set()
    for entry in getattr(book, "spine", []) or []:
        item_id = _spine_item_id(entry)
        item = documents_by_id.get(item_id)
        if item is None or item_id in seen or _is_nav_document(item):
            continue
        ordered.append((item, item_id))
        seen.add(item_id)

    if ordered:
        return ordered

    return [
        (item, _string_value(getattr(item, "id", "")))
        for item in documents
        if not _is_nav_document(item)
    ]


def inspect_epub(path: Path) -> EpubInspection:
    book = epub.read_epub(str(path))
    report = EpubInspection(
        path=path,
        title=_metadata_first(book, "DC", "title", path.stem),
        author=_metadata_first(book, "DC", "creator", "Unknown"),
        opf_identifier=_metadata_first(book, "DC", "identifier", ""),
    )

    for chapter_index, (item, item_id) in enumerate(_spine_ordered_document_items(book), start=1):
        report.chapters.append(_chapter_info(chapter_index, item, item_id))

    cover_item_ids = _cover_item_ids(book)
    epub3_cover_ids, epub3_cover_hrefs = _epub3_cover_references(path)
    cover_item_ids.update(epub3_cover_ids)
    for item in book.get_items():
        media_type = str(getattr(item, "media_type", ""))
        href = str(getattr(item, "file_name", ""))
        if media_type.startswith("image/"):
            role = "cover" if _is_cover_image(item, cover_item_ids, epub3_cover_hrefs) else "unknown"
            if role == "cover":
                report.missing_cover = False
            report.images.append(ImageInfo(href, media_type, len(item.get_content()), role))
        elif media_type == "text/css":
            css = item.get_content().decode("utf-8", errors="replace")
            report.issues.extend(_css_issues(href, css))

    if not report.chapters:
        report.issues.append(QualityIssue("HIGH", "NO_CHAPTERS", "No readable chapter documents found"))
    if report.missing_cover:
        report.issues.append(QualityIssue("MEDIUM", "MISSING_COVER", "No cover image found"))
    return report


def write_quality_report(report: EpubInspection, output_path: Path) -> Path:
    lines = [
        "# EPUB quality report",
        "",
        f"Title: {report.title}",
        f"Author: {report.author}",
        f"Identifier: {report.opf_identifier}",
        f"Chapters: {len(report.chapters)}",
        f"Images: {len(report.images)}",
        f"Missing cover: {report.missing_cover}",
        "",
        "## Issues",
    ]
    if report.issues:
        for issue in report.issues:
            lines.append(f"- [{issue.severity}] {issue.code}: {issue.message} {issue.href}".rstrip())
    else:
        lines.append("- None")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path
