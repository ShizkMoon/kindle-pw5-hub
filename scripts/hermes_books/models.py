from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class AssetMode(str, Enum):
    OFF = "off"
    COVER_ONLY = "cover-only"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class UpdateDecision(str, Enum):
    SAFE_APPEND = "SAFE_APPEND"
    SAFE_METADATA = "SAFE_METADATA"
    REVIEW_MINOR = "REVIEW_MINOR"
    BLOCKED_RISKY = "BLOCKED_RISKY"
    NEW_BOOK = "NEW_BOOK"


def _normalise_identity(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[《》「」『』\"'`]", "", value)
    return value


def canonical_id_for(title: str, author: str) -> str:
    return f"{_normalise_identity(title)}::{_normalise_identity(author)}"


def safe_slug(title: str, author: str) -> str:
    raw = f"{title.strip()} - {author.strip()}"
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw).strip(" .")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class BookJob:
    id: str
    input_path: Path
    input_format: str
    title: str
    author: str
    target_slug: str
    webdav_target_path: str
    runs_root: Path
    run_dir: Path
    asset_mode: AssetMode = AssetMode.BALANCED

    @classmethod
    def from_input(
        cls,
        input_path: Path,
        title: str,
        author: str,
        runs_root: Path,
        asset_mode: AssetMode = AssetMode.BALANCED,
        books_path: str = "/books",
    ) -> "BookJob":
        suffix = input_path.suffix.lower().lstrip(".")
        input_format = "txt" if suffix in {"txt", "text"} else suffix
        job_id = uuid.uuid4().hex
        slug = safe_slug(title, author)
        books_path = "/" + books_path.strip("/")
        return cls(
            id=job_id,
            input_path=input_path,
            input_format=input_format,
            title=title,
            author=author,
            target_slug=slug,
            webdav_target_path=f"{books_path}/{slug}.epub",
            runs_root=runs_root,
            run_dir=runs_root / job_id,
            asset_mode=asset_mode,
        )


@dataclass
class ChapterInfo:
    index: int
    title: str
    href: str
    fingerprint: str
    text_chars: int
    item_id: str = ""
    structure_fingerprint: str = ""
    resource_fingerprint: str = ""


@dataclass
class ImageInfo:
    href: str
    media_type: str
    size_bytes: int
    role: str = "unknown"


@dataclass
class QualityIssue:
    severity: str
    code: str
    message: str
    href: str = ""


@dataclass
class BookManifest:
    canonical_id: str
    title: str
    author: str
    opf_identifier: str
    source_hash: str
    output_hash: str
    update_decision: UpdateDecision = UpdateDecision.NEW_BOOK
    schema_version: int = 1
    chapter_map: list[dict[str, Any]] = field(default_factory=list)
    image_inventory: list[dict[str, Any]] = field(default_factory=list)
    quality_report: dict[str, Any] = field(default_factory=dict)
    asset_report: dict[str, Any] = field(default_factory=dict)
    previous_versions: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> str:
        def convert(value: Any) -> Any:
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, Path):
                return str(value)
            return value

        return json.dumps(asdict(self), ensure_ascii=False, indent=2, default=convert)

    @classmethod
    def from_json(cls, raw: str) -> "BookManifest":
        data = json.loads(raw)
        data["update_decision"] = UpdateDecision(data.get("update_decision", "NEW_BOOK"))
        return cls(**data)
