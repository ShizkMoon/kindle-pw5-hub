from __future__ import annotations

import html
import posixpath
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from ebooklib import epub

from scripts.txt2epub.pipeline import (
    STANDARD_CSS,
    detect_chapters,
    filter_garbage,
    merge_hard_linebreaks,
    normalize_paragraphs,
    read_text,
)

from .models import BookJob, canonical_id_for
from .textdecode import decode_markup


NORMALIZED_EPUB_CSS = """
html, body {
  margin: 0;
  padding: 0;
}
body {
  line-height: 1.6;
  widows: 2;
  orphans: 2;
}
p {
  margin: 0 0 0.8em;
  text-indent: 2em;
}
img, svg {
  max-width: 100%;
  height: auto;
}
""".strip()


def _stable_identifier(job: BookJob) -> str:
    normalized = re.sub(r"[^\w.-]+", "-", canonical_id_for(job.title, job.author)).strip("-")
    return "urn:hermes:" + (normalized or job.id)


def _chapter_file(index: int) -> str:
    return f"chapters/ch{index:04d}.xhtml"


def build_draft_from_txt(job: BookJob, raw_txt_path: Path, draft_dir: Path) -> Path:
    text = read_text(str(raw_txt_path))
    chapters = detect_chapters(text)
    chapters = [ch for ch in chapters if any(line.strip() for line in ch["content_lines"])]
    for ch in chapters:
        ch["content_lines"] = normalize_paragraphs(
            merge_hard_linebreaks(filter_garbage(ch["content_lines"]))
        )

    book = epub.EpubBook()
    book.set_identifier(_stable_identifier(job))
    book.set_title(job.title)
    book.set_language("zh")
    book.add_author(job.author)

    css_item = epub.EpubItem(
        uid="standard-css",
        file_name="styles/standard.css",
        media_type="text/css",
        content=STANDARD_CSS.encode("utf-8"),
    )
    book.add_item(css_item)

    spine: list[object] = ["nav"]
    toc: list[object] = []
    for idx, ch in enumerate(chapters, start=1):
        title = str(ch["title"])
        body = [f'<h2 id="title">{html.escape(title)}</h2>']
        for para_idx, line in enumerate(ch["content_lines"], start=1):
            stripped = line.strip()
            if stripped:
                body.append(f'<p id="p{para_idx:04d}">{html.escape(stripped)}</p>')
        chapter = epub.EpubHtml(title=title, file_name=_chapter_file(idx), lang="zh")
        chapter.content = (
            "<?xml version='1.0' encoding='utf-8'?>\n"
            "<!DOCTYPE html>\n"
            "<html xmlns='http://www.w3.org/1999/xhtml' xml:lang='zh'>"
            "<head><title>{}</title><link rel='stylesheet' type='text/css' href='../styles/standard.css'/></head>"
            "<body>{}</body></html>"
        ).format(html.escape(title), "\n".join(body)).encode("utf-8")
        chapter.add_link(href="../styles/standard.css", rel="stylesheet", type="text/css")
        book.add_item(chapter)
        spine.append(chapter)
        toc.append(epub.Link(chapter.file_name, title, f"ch{idx:04d}"))

    book.toc = toc
    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    draft_dir.mkdir(parents=True, exist_ok=True)
    output = draft_dir / f"{job.target_slug}.draft.epub"
    epub.write_epub(str(output), book)
    return output


def _opf_tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}" if namespace else name


def _opf_root_path(entries: dict[str, bytes]) -> str:
    container_ns = {"container": "urn:oasis:names:tc:opendocument:xmlns:container"}
    container = ElementTree.fromstring(entries["META-INF/container.xml"])
    rootfile = container.find(".//container:rootfile", container_ns)
    if rootfile is None:
        raise ValueError("EPUB container has no rootfile")
    opf_path = rootfile.attrib.get("full-path", "").strip()
    if not opf_path:
        raise ValueError("EPUB container rootfile has no full-path")
    return opf_path


def _unique_manifest_href(opf_path: str, entries: dict[str, bytes], requested_href: str) -> str:
    opf_dir = posixpath.dirname(opf_path)
    stem, suffix = posixpath.splitext(requested_href)
    href = requested_href
    counter = 2
    while posixpath.normpath(posixpath.join(opf_dir, href)) in entries:
        href = f"{stem}-{counter}{suffix}"
        counter += 1
    return href


def _unique_manifest_id(manifest: ElementTree.Element, namespace: str, requested_id: str) -> str:
    q = lambda name: _opf_tag(namespace, name)
    existing = {item.attrib.get("id", "") for item in manifest.findall(q("item"))}
    item_id = requested_id
    counter = 2
    while item_id in existing:
        item_id = f"{requested_id}-{counter}"
        counter += 1
    return item_id


def _relative_href(target_href: str, source_href: str) -> str:
    source_dir = posixpath.dirname(source_href)
    return posixpath.relpath(target_href, source_dir or ".")


def _inject_stylesheet_link(raw_html: bytes, stylesheet_href: str) -> bytes:
    decoded = decode_markup(raw_html)
    if not decoded.reliable:
        return raw_html
    text = decoded.text
    if stylesheet_href in text and "stylesheet" in text:
        return raw_html
    link = (
        '<link rel="stylesheet" type="text/css" '
        f'href="{html.escape(stylesheet_href, quote=True)}"/>'
    )
    text, count = re.subn(r"</head\s*>", link + "</head>", text, count=1, flags=re.IGNORECASE)
    if count == 0:
        text, count = re.subn(r"(<body\b)", f"<head>{link}</head>\\1", text, count=1, flags=re.IGNORECASE)
    if count == 0:
        text += link
    try:
        return text.encode(decoded.encoding)
    except LookupError:
        return raw_html


def normalize_existing_epub(job: BookJob, raw_epub_path: Path, normalized_dir: Path) -> Path:
    normalized_dir.mkdir(parents=True, exist_ok=True)
    output = normalized_dir / f"{job.target_slug}.normalized.epub"
    with zipfile.ZipFile(raw_epub_path, "r") as source:
        infos = source.infolist()
        entries = {info.filename: source.read(info.filename) for info in infos}

    opf_path = _opf_root_path(entries)
    opf_root = ElementTree.fromstring(entries[opf_path])
    namespace = opf_root.tag[1:].split("}", 1)[0] if opf_root.tag.startswith("{") else ""
    if namespace:
        ElementTree.register_namespace("", namespace)
    q = lambda name: _opf_tag(namespace, name)

    manifest = opf_root.find(q("manifest"))
    if manifest is None:
        manifest = ElementTree.SubElement(opf_root, q("manifest"))

    css_item = None
    css_href = ""
    for item in manifest.findall(q("item")):
        href = item.attrib.get("href", "")
        if item.attrib.get("id") == "hermes-normalized-css" or href.endswith("hermes-normalized.css"):
            css_item = item
            css_href = href
            break
    if css_item is None:
        css_href = _unique_manifest_href(opf_path, entries, "styles/hermes-normalized.css")
        css_item = ElementTree.SubElement(manifest, q("item"))
        css_item.set("id", _unique_manifest_id(manifest, namespace, "hermes-normalized-css"))
        css_item.set("href", css_href)
    css_item.set("media-type", "text/css")
    css_archive_path = posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), css_href))

    for item in manifest.findall(q("item")):
        media_type = item.attrib.get("media-type", "")
        properties = {token.lower() for token in item.attrib.get("properties", "").split()}
        href = item.attrib.get("href", "")
        if not href or media_type not in {"application/xhtml+xml", "text/html"} or "nav" in properties:
            continue
        item_path = posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), href))
        if item_path in entries:
            entries[item_path] = _inject_stylesheet_link(entries[item_path], _relative_href(css_href, href))

    entries[opf_path] = ElementTree.tostring(opf_root, encoding="utf-8", xml_declaration=True)
    entries[css_archive_path] = NORMALIZED_EPUB_CSS.encode("utf-8")

    existing_names = {info.filename for info in infos}
    with zipfile.ZipFile(output, "w") as target:
        for info in infos:
            target.writestr(info, entries[info.filename])
        for name, content in entries.items():
            if name not in existing_names:
                target.writestr(name, content)
    return output
