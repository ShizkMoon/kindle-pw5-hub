from __future__ import annotations

import posixpath
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .metadata import MetadataDecision, MetadataReport


DC_NS = "http://purl.org/dc/elements/1.1/"
OPF_NS = "http://www.idpf.org/2007/opf"


def _opf_tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}" if namespace else name


def _dc_tag(name: str) -> str:
    return f"{{{DC_NS}}}{name}"


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


def _archive_path_for_opf_href(opf_path: str, href: str) -> str:
    return posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), href))


def _media_type_suffix(media_type: str) -> str:
    if media_type == "image/png":
        return ".png"
    if media_type == "image/gif":
        return ".gif"
    if media_type == "image/webp":
        return ".webp"
    return ".jpg"


def _media_type_for_href(href: str, default: str) -> str:
    suffix = Path(href).suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix == ".gif":
        return "image/gif"
    if suffix == ".webp":
        return "image/webp"
    return default


def _normalise_values(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(part).strip() for part in value if str(part).strip()]
    return [str(value).strip()]


def _decisions_by_field(report: MetadataReport) -> dict[str, MetadataDecision]:
    return {decision.field: decision for decision in report.applied_decisions}


def _ensure_child(root: ElementTree.Element, tag: str) -> ElementTree.Element:
    child = root.find(tag)
    if child is None:
        child = ElementTree.SubElement(root, tag)
    return child


def _remove_children(parent: ElementTree.Element, tags: Iterable[str]) -> None:
    tag_set = set(tags)
    for child in list(parent):
        if child.tag in tag_set:
            parent.remove(child)


def _append_dc(metadata: ElementTree.Element, name: str, value: str) -> ElementTree.Element:
    element = ElementTree.SubElement(metadata, _dc_tag(name))
    element.text = value
    return element


def _set_meta(metadata: ElementTree.Element, namespace: str, name: str, value: Any) -> None:
    q = lambda tag_name: _opf_tag(namespace, tag_name)
    values = _normalise_values(value)
    for meta in list(metadata.findall(q("meta"))):
        if meta.attrib.get("property") == name or meta.attrib.get("name") == name:
            metadata.remove(meta)
    for item in values:
        meta = ElementTree.SubElement(metadata, q("meta"))
        meta.set("property", name)
        meta.text = item


def _unique_manifest_id(manifest: ElementTree.Element, namespace: str, requested_id: str) -> str:
    q = lambda name: _opf_tag(namespace, name)
    existing = {item.attrib.get("id", "") for item in manifest.findall(q("item"))}
    item_id = requested_id
    counter = 2
    while item_id in existing:
        item_id = f"{requested_id}-{counter}"
        counter += 1
    return item_id


def _unique_cover_href(opf_path: str, entries: dict[str, bytes], requested_href: str) -> str:
    stem, suffix = posixpath.splitext(requested_href)
    href = requested_href
    counter = 2
    while _archive_path_for_opf_href(opf_path, href) in entries:
        href = f"{stem}-{counter}{suffix}"
        counter += 1
    return href


def _write_opf_metadata(
    opf_root: ElementTree.Element,
    report: MetadataReport,
) -> None:
    namespace = opf_root.tag[1:].split("}", 1)[0] if opf_root.tag.startswith("{") else ""
    if namespace:
        ElementTree.register_namespace("", namespace)
    ElementTree.register_namespace("dc", DC_NS)
    q = lambda name: _opf_tag(namespace, name)

    metadata = _ensure_child(opf_root, q("metadata"))
    decisions = _decisions_by_field(report)

    if "title" in decisions:
        _remove_children(metadata, [_dc_tag("title")])
        for value in _normalise_values(decisions["title"].new_value):
            _append_dc(metadata, "title", value)
    if "authors" in decisions:
        _remove_children(metadata, [_dc_tag("creator")])
        for value in _normalise_values(decisions["authors"].new_value):
            _append_dc(metadata, "creator", value)
    if "publisher" in decisions:
        _remove_children(metadata, [_dc_tag("publisher")])
        for value in _normalise_values(decisions["publisher"].new_value):
            _append_dc(metadata, "publisher", value)
    if "description" in decisions:
        _remove_children(metadata, [_dc_tag("description")])
        for value in _normalise_values(decisions["description"].new_value):
            _append_dc(metadata, "description", value)
    if "subjects" in decisions:
        _remove_children(metadata, [_dc_tag("subject")])
        for value in _normalise_values(decisions["subjects"].new_value):
            _append_dc(metadata, "subject", value)
    if "isbn" in decisions:
        for value in _normalise_values(decisions["isbn"].new_value):
            identifier = _append_dc(metadata, "identifier", value)
            identifier.set(_opf_tag(OPF_NS, "scheme"), "ISBN")

    for field in [
        "original_title",
        "series",
        "volume",
        "illustrators",
        "translators",
        "imprint",
        "published_date",
    ]:
        if field in decisions:
            _set_meta(metadata, namespace, f"hermes:{field}", decisions[field].new_value)


def _write_cover(
    opf_root: ElementTree.Element,
    opf_path: str,
    entries: dict[str, bytes],
    cover_bytes: bytes,
    cover_media_type: str,
) -> str:
    namespace = opf_root.tag[1:].split("}", 1)[0] if opf_root.tag.startswith("{") else ""
    q = lambda name: _opf_tag(namespace, name)
    metadata = _ensure_child(opf_root, q("metadata"))
    manifest = _ensure_child(opf_root, q("manifest"))

    requested_href = f"images/hermes-metadata-cover{_media_type_suffix(cover_media_type)}"
    cover_href = _unique_cover_href(opf_path, entries, requested_href)
    cover_id = _unique_manifest_id(manifest, namespace, "hermes-metadata-cover")

    item = ElementTree.SubElement(manifest, q("item"))
    item.set("id", cover_id)
    item.set("href", cover_href)
    item.set("media-type", _media_type_for_href(cover_href, cover_media_type))
    item.set("properties", "cover-image")

    cover_meta = None
    for meta in metadata.findall(q("meta")):
        if meta.attrib.get("name", "").lower() == "cover":
            cover_meta = meta
            break
    if cover_meta is None:
        cover_meta = ElementTree.SubElement(metadata, q("meta"))
    cover_meta.set("name", "cover")
    cover_meta.set("content", cover_id)

    archive_path = _archive_path_for_opf_href(opf_path, cover_href)
    entries[archive_path] = cover_bytes
    return archive_path


def apply_metadata_to_epub(
    epub_path: Path,
    output_path: Path,
    report: MetadataReport,
    cover_bytes: bytes | None = None,
    cover_media_type: str = "image/jpeg",
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(epub_path, "r") as source:
        infos = source.infolist()
        entries = {info.filename: source.read(info.filename) for info in infos}

    opf_path = _opf_root_path(entries)
    opf_root = ElementTree.fromstring(entries[opf_path])
    _write_opf_metadata(opf_root, report)

    cover_path = None
    if cover_bytes is not None and any(decision.field == "cover" for decision in report.applied_decisions):
        cover_path = _write_cover(opf_root, opf_path, entries, cover_bytes, cover_media_type)

    entries[opf_path] = ElementTree.tostring(opf_root, encoding="utf-8", xml_declaration=True)
    existing_names = {info.filename for info in infos}

    with zipfile.ZipFile(output_path, "w") as target:
        for info in infos:
            target.writestr(info, entries[info.filename])
        for name, content in entries.items():
            if name not in existing_names:
                target.writestr(name, content)
        if cover_path and cover_path in existing_names:
            target.writestr(cover_path, entries[cover_path])
    return output_path
