from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

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
            for candidate in candidates:
                if self.config.require_source_url and not candidate.source_url:
                    report.pending.append(candidate)
                elif candidate.confidence >= threshold:
                    report.auto_adopted.append(candidate)
                else:
                    report.pending.append(candidate)
        return report
