from __future__ import annotations

import hashlib
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit
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
        self._ignored_heading_depth = 0
        self._body_content_seen = False
        self._texts: list[str] = []
        self._structure: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._enter_tag(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "head":
            return
        if self._body_depth and not self._ignored_depth:
            self._structure.append(f"<{self._structure_tag(tag, attrs)}/>")
            if not self._ignored_heading_depth:
                self._body_content_seen = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "head" and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if self._ignored_heading_depth:
            if tag != "body":
                self._structure.append(f"</{tag}>")
            if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                self._ignored_heading_depth -= 1
                if not self._ignored_heading_depth:
                    self._body_content_seen = True
            return
        if self._body_depth and tag != "body":
            self._structure.append(f"</{tag}>")
            self._body_content_seen = True
        if tag == "body" and self._body_depth:
            self._body_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._body_depth and not self._ignored_depth and not self._ignored_heading_depth:
            self._texts.append(data)
            text = _normalise_text(data)
            if text:
                self._structure.append(f"text:{text}")
                self._body_content_seen = True

    def text(self) -> str:
        return "".join(self._texts)

    def structure(self) -> str:
        return "\n".join(self._structure)

    def _enter_tag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "body":
            self._body_depth += 1
            if attrs:
                self._structure.append(f"<{self._structure_tag(tag, attrs)}>")
            return
        if tag == "head":
            self._ignored_depth += 1
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and self._body_depth and not self._body_content_seen:
            self._structure.append(f"<{self._structure_tag(tag, attrs)}>")
            self._ignored_heading_depth += 1
            return
        if self._body_depth and not self._ignored_depth and tag != "body":
            self._structure.append(f"<{self._structure_tag(tag, attrs)}>")
            if not self._ignored_heading_depth:
                self._body_content_seen = True

    def _structure_tag(self, tag: str, attrs: list[tuple[str, str | None]]) -> str:
        anchors = []
        for key, value in attrs:
            if key and value:
                attr = key.lower()
                anchors.append(f'{attr}="{_normalise_structure_attr(attr, value)}"')
        return " ".join([tag, *sorted(anchors)])


def _normalise_text(raw: str) -> str:
    cjk = "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    text = raw.replace("\xa0", " ")
    text = re.sub(fr"(?<=[{cjk}])\s+(?=[{cjk}])", "", text)
    return re.sub(r"\s+", " ", text).strip()


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
    parsed = urlsplit(href)
    href_path = parsed.path if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment else href
    normalised = posixpath.normpath(unquote(href_path).replace("\\", "/").lstrip("/"))
    return "" if normalised == "." else normalised


def _normalise_structure_reference(href: str) -> str:
    value = href.strip()
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return value

    base = _normalise_epub_href(value)
    suffix = ""
    if parsed.query:
        suffix += f"?{unquote(parsed.query)}"
    if parsed.fragment:
        suffix += f"#{unquote(parsed.fragment)}"
    return f"{base}{suffix}"


def _srcset_references(value: str) -> list[str]:
    references: list[str] = []
    for candidate in value.split(","):
        parts = candidate.strip().split()
        if parts:
            references.append(parts[0])
    return references


def _normalise_srcset(value: str) -> str:
    return ", ".join(_normalise_structure_reference(reference) for reference in _srcset_references(value))


def _normalise_structure_attr(attr: str, value: str) -> str:
    clean = value.strip()
    if attr in {"href", "src", "poster"} or attr.endswith(":href"):
        return _normalise_structure_reference(clean)
    if attr == "srcset":
        return _normalise_srcset(clean)
    if attr == "class":
        return " ".join(sorted(clean.split()))
    return re.sub(r"\s+", " ", clean)


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


def _epub_raw_entries(path: Path) -> tuple[str, dict[str, bytes]]:
    container_ns = {"container": "urn:oasis:names:tc:opendocument:xmlns:container"}
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    try:
        container = ElementTree.fromstring(entries["META-INF/container.xml"])
        rootfile = container.find(".//container:rootfile", container_ns)
    except (KeyError, ElementTree.ParseError):
        return "", entries
    if rootfile is None:
        return "", entries
    return _string_value(rootfile.attrib.get("full-path")), entries


def _resource_contents_by_href(opf_path: str, entries: dict[str, bytes]) -> dict[str, bytes]:
    if not opf_path:
        return {}
    opf_dir = posixpath.dirname(_normalise_epub_href(opf_path))
    prefix = f"{opf_dir}/" if opf_dir else ""
    contents: dict[str, bytes] = {}
    for archive_name, content in entries.items():
        normalised = _normalise_epub_href(archive_name)
        if prefix and not normalised.startswith(prefix):
            continue
        href = normalised[len(prefix):] if prefix else normalised
        contents[href] = content
    return contents


def _raw_item_content(
    item: epub.EpubItem,
    resource_content_by_href: dict[str, bytes],
) -> bytes:
    href = _normalise_epub_href(str(getattr(item, "file_name", "")))
    return resource_content_by_href.get(href, item.get_content())


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


def _resource_references(raw_html: bytes) -> list[str]:
    class ReferenceParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.references: list[str] = []
            self.inline_css: list[str] = []
            self._style_depth = 0

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag.lower() == "style":
                self._style_depth += 1
            self._collect(attrs)

        def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self._collect(attrs)

        def handle_endtag(self, tag: str) -> None:
            if tag.lower() == "style" and self._style_depth:
                self._style_depth -= 1

        def handle_data(self, data: str) -> None:
            if self._style_depth:
                self.inline_css.append(data)

        def _collect(self, attrs: list[tuple[str, str | None]]) -> None:
            for key, value in attrs:
                if not key or not value:
                    continue
                attr = key.lower()
                if attr in {"src", "href", "poster"} or attr.endswith(":href"):
                    if not value.startswith("#"):
                        self.references.append(value)
                elif attr == "srcset":
                    self.references.extend(_srcset_references(value))
                elif attr == "style":
                    self.inline_css.append(value)

    parser = ReferenceParser()
    parser.feed(raw_html.decode("utf-8", errors="replace"))
    parser.close()
    for css in parser.inline_css:
        parser.references.extend(_css_url_references(css))
    return parser.references


def _resource_href(raw_reference: str) -> str:
    parsed = urlsplit(raw_reference)
    return parsed.path if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment else raw_reference


def _normalise_resource_reference(raw_reference: str, base_dir: str) -> str:
    reference = raw_reference.strip()
    parsed = urlsplit(reference)
    if parsed.scheme or parsed.netloc:
        return reference
    if reference.startswith("#"):
        return reference

    base = _normalise_epub_href(posixpath.join(base_dir, _resource_href(reference)))
    suffix = ""
    if parsed.query:
        suffix += f"?{unquote(parsed.query)}"
    if parsed.fragment:
        suffix += f"#{unquote(parsed.fragment)}"
    return f"{base}{suffix}"


def _css_url_references(css: bytes | str) -> list[str]:
    text = css.decode("utf-8", errors="replace") if isinstance(css, bytes) else css
    return [
        match.group(2).strip()
        for match in re.finditer(r"url\(\s*(['\"]?)(.*?)\1\s*\)", text, re.IGNORECASE)
        if match.group(2).strip()
    ]


def _resource_fingerprint(
    item: epub.EpubItem,
    raw_content: bytes,
    resources_by_href: dict[str, epub.EpubItem],
    resource_content_by_href: dict[str, bytes],
    spine_hrefs: set[str],
) -> str:
    chapter_href = _normalise_epub_href(str(getattr(item, "file_name", "")))
    chapter_dir = posixpath.dirname(chapter_href)
    parts: list[str] = []
    visited: set[str] = set()

    def append_reference(raw_reference: str, base_dir: str) -> None:
        raw_reference = raw_reference.strip()
        if not raw_reference:
            return
        parts.append(f"ref:{_normalise_resource_reference(raw_reference, base_dir)}")
        if raw_reference.startswith(("http://", "https://", "mailto:", "data:")):
            parts.append(f"external:{raw_reference}")
            return
        if raw_reference.startswith("#"):
            return

        normalised = _normalise_epub_href(posixpath.join(base_dir, _resource_href(raw_reference)))
        referenced = resources_by_href.get(normalised)
        if referenced is None:
            parts.append(f"missing:{normalised}")
            return

        media_type = str(getattr(referenced, "media_type", ""))
        if media_type == "application/xhtml+xml" and (
            normalised == chapter_href or normalised in spine_hrefs
        ):
            return
        if normalised in visited:
            return

        visited.add(normalised)
        content = resource_content_by_href.get(normalised, referenced.get_content())
        parts.append(f"{normalised}:{media_type}:{hashlib.sha256(content).hexdigest()}")
        resource_dir = posixpath.dirname(normalised)
        if media_type == "text/css":
            for css_reference in sorted(set(_css_url_references(content))):
                append_reference(css_reference, resource_dir)
        elif media_type == "application/xhtml+xml" or media_type == "image/svg+xml" or media_type.endswith("+xml"):
            for nested_reference in sorted(set(_resource_references(content))):
                append_reference(nested_reference, resource_dir)

    for raw_reference in sorted(set(_resource_references(raw_content))):
        append_reference(raw_reference, chapter_dir)
    return hashlib.sha256("\n".join(sorted(set(parts))).encode("utf-8")).hexdigest()


def _spine_itemref_fingerprints(path: Path) -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    container_ns = {"container": "urn:oasis:names:tc:opendocument:xmlns:container"}
    opf_ns = {"opf": "http://www.idpf.org/2007/opf"}
    try:
        with zipfile.ZipFile(path) as archive:
            container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
            rootfile = container.find(".//container:rootfile", container_ns)
            if rootfile is None:
                return fingerprints
            opf_path = _string_value(rootfile.attrib.get("full-path"))
            if not opf_path:
                return fingerprints
            opf_root = ElementTree.fromstring(archive.read(opf_path))
    except (KeyError, ElementTree.ParseError, zipfile.BadZipFile):
        return fingerprints

    for itemref in opf_root.findall(".//opf:spine/opf:itemref", opf_ns):
        item_id = _string_value(itemref.attrib.get("idref"))
        if not item_id:
            continue
        attrs = [
            f'{key.lower()}="{_normalise_structure_attr(key.lower(), value)}"'
            for key, value in itemref.attrib.items()
            if key.lower() != "idref" and value
        ]
        fingerprints[item_id] = " ".join(sorted(attrs))
    return fingerprints


def _chapter_info(
    index: int,
    item: epub.EpubItem,
    item_id: str,
    raw_content: bytes,
    resources_by_href: dict[str, epub.EpubItem],
    resource_content_by_href: dict[str, bytes],
    spine_hrefs: set[str],
    spine_itemref_fingerprint: str = "",
) -> ChapterInfo:
    href = str(getattr(item, "file_name", ""))
    fingerprint, text_chars, structure_fingerprint = _fingerprint(raw_content)
    if spine_itemref_fingerprint:
        structure_fingerprint = hashlib.sha256(
            f"{structure_fingerprint}\nspine:{spine_itemref_fingerprint}".encode("utf-8")
        ).hexdigest()
    resource_fingerprint = _resource_fingerprint(
        item,
        raw_content,
        resources_by_href,
        resource_content_by_href,
        spine_hrefs,
    )
    title = _string_value(getattr(item, "title", "")) or href
    return ChapterInfo(
        index,
        title,
        href,
        fingerprint,
        text_chars,
        item_id,
        structure_fingerprint,
        resource_fingerprint,
    )


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
    opf_path, raw_entries = _epub_raw_entries(path)
    resource_content_by_href = _resource_contents_by_href(opf_path, raw_entries)
    report = EpubInspection(
        path=path,
        title=_metadata_first(book, "DC", "title", path.stem),
        author=_metadata_first(book, "DC", "creator", "Unknown"),
        opf_identifier=_metadata_first(book, "DC", "identifier", ""),
    )

    resources_by_href = {
        _normalise_epub_href(str(getattr(item, "file_name", ""))): item
        for item in book.get_items()
        if str(getattr(item, "file_name", ""))
    }
    ordered_items = _spine_ordered_document_items(book)
    spine_itemrefs = _spine_itemref_fingerprints(path)
    spine_hrefs = {
        _normalise_epub_href(str(getattr(item, "file_name", "")))
        for item, _ in ordered_items
    }
    for chapter_index, (item, item_id) in enumerate(ordered_items, start=1):
        report.chapters.append(
            _chapter_info(
                chapter_index,
                item,
                item_id,
                _raw_item_content(item, resource_content_by_href),
                resources_by_href,
                resource_content_by_href,
                spine_hrefs,
                spine_itemrefs.get(item_id, ""),
            )
        )

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
