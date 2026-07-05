from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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


def _normalise_text(raw: str) -> str:
    raw = re.sub(r"<[^>]+>", "", raw)
    return re.sub(r"\s+", "", raw)


def _fingerprint(raw_html: bytes) -> tuple[str, int]:
    text = _normalise_text(raw_html.decode("utf-8", errors="replace"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), len(text)


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
    name = str(getattr(item, "file_name", "")).lower()
    if name.endswith(("nav.xhtml", "nav.html")):
        return True
    return "nav" in str(getattr(item, "properties", "")).lower()


def inspect_epub(path: Path) -> EpubInspection:
    book = epub.read_epub(str(path))
    report = EpubInspection(
        path=path,
        title=_metadata_first(book, "DC", "title", path.stem),
        author=_metadata_first(book, "DC", "creator", "Unknown"),
        opf_identifier=_metadata_first(book, "DC", "identifier", ""),
    )

    chapter_index = 1
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        if _is_nav_document(item):
            continue
        href = str(getattr(item, "file_name", ""))
        fingerprint, text_chars = _fingerprint(item.get_content())
        title = _string_value(getattr(item, "title", "")) or href
        report.chapters.append(ChapterInfo(chapter_index, title, href, fingerprint, text_chars))
        chapter_index += 1

    for item in book.get_items():
        media_type = str(getattr(item, "media_type", ""))
        href = str(getattr(item, "file_name", ""))
        if media_type.startswith("image/"):
            role = "cover" if "cover" in href.lower() else "unknown"
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
