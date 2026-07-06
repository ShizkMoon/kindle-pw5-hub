from __future__ import annotations

import hashlib
import json
import posixpath
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol
from xml.etree import ElementTree

from .config import AssetEnrichmentConfig
from .inspect import EpubInspection
from .models import AssetMode


@dataclass
class AssetCandidate:
    role: str
    source_url: str
    local_path: Path
    width: int
    height: int
    confidence: float
    reason: str


@dataclass
class AssetReport:
    auto_adopted: list[AssetCandidate] = field(default_factory=list)
    pending: list[AssetCandidate] = field(default_factory=list)
    missing_roles: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        def convert(value):
            if isinstance(value, Path):
                return str(value)
            return value

        return json.dumps(asdict(self), ensure_ascii=False, indent=2, default=convert)


class AssetProvider(Protocol):
    def candidates(self, title: str, author: str, role: str) -> list[AssetCandidate]:
        ...


class AssetFetcher(Protocol):
    def fetch(self, candidate: AssetCandidate, cache_dir: Path) -> Path:
        ...


class GoogleBooksCoverProvider:
    def candidates(self, title: str, author: str, role: str) -> list[AssetCandidate]:
        if role != "cover":
            return []

        query = urllib.parse.urlencode({"q": f'intitle:"{title}" inauthor:"{author}"'})
        url = f"https://www.googleapis.com/books/v1/volumes?{query}"
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return []

        candidates: list[AssetCandidate] = []
        for item in data.get("items", [])[:3]:
            image_links = item.get("volumeInfo", {}).get("imageLinks", {})
            cover_url = (
                image_links.get("extraLarge")
                or image_links.get("large")
                or image_links.get("thumbnail")
            )
            if not cover_url:
                continue
            candidates.append(
                AssetCandidate(
                    role="cover",
                    source_url=cover_url.replace("http://", "https://"),
                    local_path=Path(""),
                    width=0,
                    height=0,
                    confidence=0.86,
                    reason="Google Books title/author cover candidate",
                )
            )
        return candidates


class UrlAssetFetcher:
    def fetch(self, candidate: AssetCandidate, cache_dir: Path) -> Path:
        if not candidate.source_url:
            raise ValueError("candidate has no source URL")

        cache_dir.mkdir(parents=True, exist_ok=True)
        suffix = _image_suffix(Path(urllib.parse.urlparse(candidate.source_url).path).suffix)
        digest = hashlib.sha256(candidate.source_url.encode("utf-8")).hexdigest()[:16]
        target = cache_dir / f"{candidate.role}-{digest}{suffix}"
        if not target.exists():
            with urllib.request.urlopen(candidate.source_url, timeout=30) as resp:
                target.write_bytes(resp.read())
        return target


class AssetEnricher:
    def __init__(self, config: AssetEnrichmentConfig, provider: AssetProvider | None = None) -> None:
        self.config = config
        self.provider = provider or GoogleBooksCoverProvider()

    def plan(
        self,
        title: str,
        author: str,
        inspection: EpubInspection,
        cache_dir: Path,
    ) -> AssetReport:
        report = AssetReport()
        if self.config.mode == AssetMode.OFF:
            return report

        roles: list[str] = []
        cover_modes = {AssetMode.COVER_ONLY, AssetMode.BALANCED, AssetMode.AGGRESSIVE}
        if inspection.missing_cover and self.config.mode in cover_modes:
            roles.append("cover")
        if self.config.mode == AssetMode.AGGRESSIVE:
            roles.append("illustration")

        for role in roles:
            try:
                candidates = self.provider.candidates(title, author, role)
            except Exception as exc:
                report.errors.append(f"{role}: {exc}")
                candidates = []

            if not candidates:
                report.missing_roles.append(role)
                continue

            threshold = (
                self.config.auto_cover_min_confidence
                if role == "cover"
                else self.config.auto_insert_illustration_min_confidence
            )
            adopted_for_role = False
            for candidate in candidates:
                if self.config.require_source_url and not candidate.source_url:
                    report.pending.append(candidate)
                elif role != "cover":
                    report.pending.append(candidate)
                elif candidate.confidence >= threshold and not adopted_for_role:
                    report.auto_adopted.append(candidate)
                    adopted_for_role = True
                else:
                    report.pending.append(candidate)
        return report


def _image_suffix(raw_suffix: str) -> str:
    suffix = raw_suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        return suffix
    return ".jpg"


def _existing_candidate_path(candidate: AssetCandidate, cache_dir: Path) -> Path | None:
    if not str(candidate.local_path):
        return None
    path = candidate.local_path
    if not path.is_absolute():
        cache_root = cache_dir.resolve()
        path = (cache_root / path).resolve()
        try:
            path.relative_to(cache_root)
        except ValueError:
            return None
    if path.exists() and path.is_file():
        return path
    return None


def _read_candidate(
    candidate: AssetCandidate,
    cache_dir: Path,
    fetcher: AssetFetcher | None,
) -> tuple[bytes, Path]:
    local_path = _existing_candidate_path(candidate, cache_dir)
    if local_path is not None:
        return local_path.read_bytes(), local_path

    fetched_path = (fetcher or UrlAssetFetcher()).fetch(candidate, cache_dir)
    return fetched_path.read_bytes(), fetched_path


def _cover_file_name(candidate: AssetCandidate, source_path: Path) -> str:
    suffix = _image_suffix(source_path.suffix or Path(urllib.parse.urlparse(candidate.source_url).path).suffix)
    return f"images/hermes-cover{suffix}"


def _media_type(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".gif":
        return "image/gif"
    if suffix == ".webp":
        return "image/webp"
    return "image/jpeg"


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


def _ensure_cover_manifest(opf: ElementTree.Element, file_name: str) -> None:
    namespace = opf.tag[1:].split("}", 1)[0] if opf.tag.startswith("{") else ""
    if namespace:
        ElementTree.register_namespace("", namespace)
    q = lambda name: _opf_tag(namespace, name)

    metadata = opf.find(q("metadata"))
    if metadata is None:
        metadata = ElementTree.Element(q("metadata"))
        opf.insert(0, metadata)

    cover_id = "hermes-cover-image"
    cover_meta = None
    for meta in metadata.findall(q("meta")):
        if meta.attrib.get("name", "").lower() == "cover":
            cover_meta = meta
            break
    if cover_meta is None:
        cover_meta = ElementTree.SubElement(metadata, q("meta"))
    cover_meta.set("name", "cover")
    cover_meta.set("content", cover_id)

    manifest = opf.find(q("manifest"))
    if manifest is None:
        manifest = ElementTree.SubElement(opf, q("manifest"))

    cover_item = None
    for item in manifest.findall(q("item")):
        if item.attrib.get("id") == cover_id:
            cover_item = item
            break
    if cover_item is None:
        cover_item = ElementTree.SubElement(manifest, q("item"))
    cover_item.set("id", cover_id)
    cover_item.set("href", file_name)
    cover_item.set("media-type", _media_type(file_name))
    if opf.attrib.get("version", "").startswith("3"):
        properties = {token for token in cover_item.attrib.get("properties", "").split() if token}
        properties.add("cover-image")
        cover_item.set("properties", " ".join(sorted(properties)))


def _archive_path_for_opf_href(opf_path: str, href: str) -> str:
    return posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), href))


def _existing_cover_archive_paths(opf: ElementTree.Element, opf_path: str) -> set[str]:
    namespace = opf.tag[1:].split("}", 1)[0] if opf.tag.startswith("{") else ""
    q = lambda name: _opf_tag(namespace, name)
    cover_ids = {"hermes-cover-image"}
    metadata = opf.find(q("metadata"))
    if metadata is not None:
        for meta in metadata.findall(q("meta")):
            if meta.attrib.get("name", "").lower() == "cover":
                cover_id = meta.attrib.get("content", "").strip()
                if cover_id:
                    cover_ids.add(cover_id)

    paths: set[str] = set()
    manifest = opf.find(q("manifest"))
    if manifest is None:
        return paths
    for item in manifest.findall(q("item")):
        item_id = item.attrib.get("id", "")
        properties = {token.lower() for token in item.attrib.get("properties", "").split()}
        href = item.attrib.get("href", "")
        if href and (item_id in cover_ids or "cover-image" in properties):
            paths.add(_archive_path_for_opf_href(opf_path, href))
    return paths


def _unique_cover_file_name(
    opf: ElementTree.Element,
    opf_path: str,
    entries: dict[str, bytes],
    file_name: str,
) -> str:
    image_path = _archive_path_for_opf_href(opf_path, file_name)
    if image_path not in entries or image_path in _existing_cover_archive_paths(opf, opf_path):
        return file_name

    stem, suffix = posixpath.splitext(file_name)
    counter = 2
    while True:
        candidate = f"{stem}-{counter}{suffix}"
        if _archive_path_for_opf_href(opf_path, candidate) not in entries:
            return candidate
        counter += 1


def _insert_cover(epub_path: Path, file_name: str, data: bytes) -> None:
    temp_path = epub_path.with_name(f"{epub_path.stem}.assets.tmp{epub_path.suffix}")
    with zipfile.ZipFile(epub_path, "r") as source:
        infos = source.infolist()
        entries = {info.filename: source.read(info.filename) for info in infos}

    opf_path = _opf_root_path(entries)
    opf = ElementTree.fromstring(entries[opf_path])
    file_name = _unique_cover_file_name(opf, opf_path, entries, file_name)
    _ensure_cover_manifest(opf, file_name)
    entries[opf_path] = ElementTree.tostring(opf, encoding="utf-8", xml_declaration=True)

    image_path = _archive_path_for_opf_href(opf_path, file_name)
    entries[image_path] = data
    existing_names = {info.filename for info in infos}

    try:
        with zipfile.ZipFile(temp_path, "w") as target:
            for info in infos:
                if info.filename == opf_path:
                    target.writestr(info, entries[opf_path])
                elif info.filename == image_path:
                    target.writestr(info, data)
                else:
                    target.writestr(info, entries[info.filename])
            if image_path not in existing_names:
                target.writestr(image_path, data)
        temp_path.replace(epub_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def apply_auto_adopted_assets(
    epub_path: Path,
    report: AssetReport,
    cache_dir: Path,
    fetcher: AssetFetcher | None = None,
) -> bool:
    changed = False
    for candidate in report.auto_adopted:
        if candidate.role != "cover":
            continue
        try:
            data, source_path = _read_candidate(candidate, cache_dir, fetcher)
            _insert_cover(epub_path, _cover_file_name(candidate, source_path), data)
            candidate.local_path = source_path
            changed = True
        except Exception as exc:
            report.errors.append(f"{candidate.role}: auto-adoption failed: {exc}")
    return changed
