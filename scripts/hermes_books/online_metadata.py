from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .config import OnlineEnrichmentConfig
from .metadata import (
    MetadataClues,
    MetadataDecision,
    MetadataEvidence,
    MetadataReport,
    MetadataResolution,
)


JsonFetcher = Callable[[str], dict[str, Any]]


def _normalise_identity(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^\w\u3400-\u9fff\uf900-\ufaff]+", "", value)


def _similarity(left: str, right: str) -> float:
    left_normalized = _normalise_identity(left)
    right_normalized = _normalise_identity(right)
    if not left_normalized or not right_normalized:
        return 0.0
    if left_normalized == right_normalized:
        return 1.0
    if left_normalized in right_normalized or right_normalized in left_normalized:
        shorter = min(len(left_normalized), len(right_normalized))
        longer = max(len(left_normalized), len(right_normalized))
        return 0.9 + 0.1 * (shorter / longer)
    return SequenceMatcher(None, left_normalized, right_normalized).ratio()


def _identity_score(
    expected_title: str,
    expected_author: str,
    candidate_title: str,
    candidate_authors: list[str],
) -> float:
    title_score = _similarity(expected_title, candidate_title)
    author_score = max((_similarity(expected_author, author) for author in candidate_authors), default=0.0)
    if not expected_author.strip():
        return title_score
    return 0.72 * title_score + 0.28 * author_score


def _string_list(value: Any, *, limit: int = 20) -> list[str]:
    raw_values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for raw in raw_values:
        text = str(raw).strip() if raw is not None else ""
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _first_string(value: Any) -> str:
    values = _string_list(value, limit=1)
    return values[0] if values else ""


def _clean_description(value: Any) -> str:
    raw = _first_string(value)
    if not raw:
        return ""
    without_tags = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()[:20_000]


def _valid_isbn(value: str) -> bool:
    if len(value) == 13 and value.isdigit():
        expected = (10 - sum((1 if index % 2 == 0 else 3) * int(char) for index, char in enumerate(value[:12])) % 10) % 10
        return expected == int(value[-1])
    if len(value) == 10 and value[:9].isdigit() and (value[-1].isdigit() or value[-1] == "X"):
        digits = [int(char) for char in value[:9]] + [10 if value[-1] == "X" else int(value[-1])]
        return sum((10 - index) * digit for index, digit in enumerate(digits)) % 11 == 0
    return False


def _best_isbn(values: Any) -> str:
    candidates: list[str] = []
    if isinstance(values, list):
        for value in values:
            if isinstance(value, dict):
                identifier = str(value.get("identifier", "")).strip()
            else:
                identifier = str(value).strip()
            normalized = re.sub(r"[^0-9Xx]", "", identifier).upper()
            if _valid_isbn(normalized) and normalized not in candidates:
                candidates.append(normalized)
    return next((isbn for isbn in candidates if len(isbn) == 13), candidates[0] if candidates else "")


def _best_google_cover(image_links: Any) -> str:
    if not isinstance(image_links, dict):
        return ""
    for key in ("extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail"):
        url = str(image_links.get(key, "")).strip()
        if url:
            return url.replace("http://", "https://", 1)
    return ""


def _redact_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    redacted_query = [
        (key, "REDACTED" if key.lower() in {"key", "api_key", "apikey"} else value)
        for key, value in query
    ]
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(redacted_query), parsed.fragment)
    )


class CachedJsonFetcher:
    def __init__(
        self,
        config: OnlineEnrichmentConfig,
        cache_dir: Path,
        evidence_dir: Path | None = None,
    ) -> None:
        self.config = config
        self.cache_dir = cache_dir
        self.evidence_dir = evidence_dir

    def _write_evidence_copy(self, digest: str, payload: dict[str, Any]) -> None:
        if self.evidence_dir is None:
            return
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        (self.evidence_dir / f"{digest}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def __call__(self, url: str) -> dict[str, Any]:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        cache_path = self.cache_dir / f"{digest}.json"
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                age_seconds = time.time() - float(cached.get("fetched_at", 0))
                if age_seconds <= self.config.cache_ttl_hours * 3600:
                    body = cached.get("body")
                    if isinstance(body, dict):
                        self._write_evidence_copy(digest, cached)
                        return body
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass

        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": self.config.user_agent,
            },
        )
        with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
            raw = response.read(self.config.max_response_bytes + 1)
        if len(raw) > self.config.max_response_bytes:
            raise ValueError(f"metadata response exceeds {self.config.max_response_bytes} bytes")
        body = json.loads(raw.decode("utf-8"))
        if not isinstance(body, dict):
            raise ValueError("metadata response is not a JSON object")

        cache_payload = {
            "url": _redact_url(url),
            "fetched_at": time.time(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "body": body,
        }
        temp_path = cache_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(cache_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(cache_path)
        self._write_evidence_copy(digest, cache_payload)
        return body


class OnlineMetadataProvider:
    def __init__(
        self,
        config: OnlineEnrichmentConfig,
        cache_dir: Path,
        fetch_json: JsonFetcher | None = None,
        evidence_dir: Path | None = None,
    ) -> None:
        self.config = config
        self.fetch_json = fetch_json or CachedJsonFetcher(config, cache_dir, evidence_dir)
        self.errors: list[str] = []

    def search(self, clues: MetadataClues) -> list[MetadataEvidence]:
        self.errors = []
        evidence: list[MetadataEvidence] = []
        sources = {
            source.strip().lower()
            for source in self.config.sources.split(",")
            if source.strip()
        }
        if "google-books" in sources:
            try:
                evidence.extend(self._search_google_books(clues))
            except Exception as exc:
                self.errors.append(f"google-books: {exc}")
        if "open-library" in sources:
            try:
                evidence.extend(self._search_open_library(clues))
            except Exception as exc:
                self.errors.append(f"open-library: {exc}")
        unknown_sources = sources - {"google-books", "open-library"}
        self.errors.extend(f"unsupported online metadata source: {source}" for source in sorted(unknown_sources))
        return evidence

    def _search_google_books(self, clues: MetadataClues) -> list[MetadataEvidence]:
        params = {
            "q": f'intitle:"{clues.title}" inauthor:"{clues.author}"',
            "maxResults": self.config.max_results_per_source,
            "printType": "books",
            "projection": "full",
        }
        api_key = os.environ.get(self.config.google_books_api_key_env, "").strip()
        if api_key:
            params["key"] = api_key
        query_url = "https://www.googleapis.com/books/v1/volumes?" + urllib.parse.urlencode(params)
        payload = self.fetch_json(query_url)
        evidence: list[MetadataEvidence] = []
        items = payload.get("items", [])
        if not isinstance(items, list):
            return []
        for rank, item in enumerate(items[: self.config.max_results_per_source]):
            if not isinstance(item, dict):
                continue
            info = item.get("volumeInfo", {})
            if not isinstance(info, dict):
                continue
            title = str(info.get("title", "")).strip()
            authors = _string_list(info.get("authors"))
            score = _identity_score(clues.title, clues.author, title, authors)
            if score < self.config.min_identity_score:
                continue
            facts: dict[str, Any] = {
                "title": title,
                "authors": authors,
                "publisher": _first_string(info.get("publisher")),
                "published_date": _first_string(info.get("publishedDate")),
                "description": _clean_description(info.get("description")),
                "subjects": _string_list(info.get("categories"), limit=12),
                "isbn": _best_isbn(info.get("industryIdentifiers")),
                "cover": _best_google_cover(info.get("imageLinks")),
                "language": _first_string(info.get("language")),
            }
            facts = {
                key: value
                for key, value in facts.items()
                if value is not None and value != "" and value != []
            }
            volume_id = str(item.get("id", "")).strip() or f"rank-{rank + 1}"
            record_url = (
                str(info.get("canonicalVolumeLink", "")).strip()
                or str(info.get("infoLink", "")).strip()
                or f"https://books.google.com/books?id={urllib.parse.quote(volume_id)}"
            )
            confidence = max(0.0, min(0.99, score * 0.98 - rank * 0.02))
            evidence.append(
                MetadataEvidence(
                    id=f"google-books:{volume_id}",
                    source="google-books",
                    url=record_url.replace("http://", "https://", 1),
                    facts=facts,
                    confidence=confidence,
                )
            )
        return evidence

    def _search_open_library(self, clues: MetadataClues) -> list[MetadataEvidence]:
        fields = "key,title,author_name,cover_i,isbn,publisher,first_publish_year,subject"
        params = {
            "title": clues.title,
            "author": clues.author,
            "fields": fields,
            "limit": self.config.max_results_per_source,
        }
        query_url = "https://openlibrary.org/search.json?" + urllib.parse.urlencode(params)
        payload = self.fetch_json(query_url)
        evidence: list[MetadataEvidence] = []
        documents = payload.get("docs", [])
        if not isinstance(documents, list):
            return []
        for rank, item in enumerate(documents[: self.config.max_results_per_source]):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            authors = _string_list(item.get("author_name"))
            score = _identity_score(clues.title, clues.author, title, authors)
            if score < self.config.min_identity_score:
                continue
            cover_id = item.get("cover_i")
            cover_url = (
                f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg?default=false"
                if isinstance(cover_id, int) and cover_id > 0
                else ""
            )
            facts: dict[str, Any] = {
                "title": title,
                "authors": authors,
                "publisher": _first_string(item.get("publisher")),
                "subjects": _string_list(item.get("subject"), limit=12),
                "isbn": _best_isbn(item.get("isbn")),
                "cover": cover_url,
                "first_published_year": item.get("first_publish_year", ""),
            }
            facts = {
                key: value
                for key, value in facts.items()
                if value is not None and value != "" and value != []
            }
            key = str(item.get("key", "")).strip()
            record_id = key.strip("/").replace("/", ":") or f"rank-{rank + 1}"
            record_url = "https://openlibrary.org" + key if key.startswith("/") else "https://openlibrary.org"
            confidence = max(0.0, min(0.97, score * 0.96 - rank * 0.02))
            evidence.append(
                MetadataEvidence(
                    id=f"open-library:{record_id}",
                    source="open-library",
                    url=record_url,
                    facts=facts,
                    confidence=confidence,
                )
            )
        return evidence


def _canonical_fact(value: Any) -> str:
    if isinstance(value, list):
        return json.dumps(sorted(_normalise_identity(str(item)) for item in value), ensure_ascii=False)
    return _normalise_identity(str(value))


def _has_value(value: Any) -> bool:
    return value is not None and value != "" and value != []


class DeterministicMetadataReasoner:
    FIELDS = ("publisher", "description", "subjects", "isbn", "published_date", "cover")

    def resolve(
        self,
        clues: MetadataClues,
        evidence: list[MetadataEvidence],
    ) -> MetadataResolution:
        decisions: list[MetadataDecision] = []
        existing = clues.existing_metadata
        for field in self.FIELDS:
            candidates = [item for item in evidence if _has_value(item.facts.get(field))]
            if not candidates:
                continue
            groups: dict[str, list[MetadataEvidence]] = {}
            for item in candidates:
                groups.setdefault(_canonical_fact(item.facts[field]), []).append(item)
            ranked_groups = sorted(
                groups.values(),
                key=lambda group: (
                    len({item.source for item in group}),
                    max(item.confidence for item in group),
                ),
                reverse=True,
            )
            selected_group = ranked_groups[0]
            selected = max(selected_group, key=lambda item: item.confidence)
            source_count = len({item.source for item in selected_group})
            confidence = min(0.99, selected.confidence + 0.03 * (source_count - 1))
            old_value = "" if field == "cover" else existing.get(field, "")
            if field == "cover" and not bool(existing.get("missing_cover", True)):
                old_value = "existing-cover"
            new_value = selected.facts[field]

            if _has_value(old_value):
                if _canonical_fact(old_value) == _canonical_fact(new_value):
                    continue
                action = "review"
                reason = "existing value differs; preserve the EPUB value pending review"
            else:
                action = "apply"
                reason = f"best identity-matched evidence from {source_count} source(s)"

            if field == "isbn" and source_count < 2:
                action = "review"
                reason = "edition-specific ISBN requires agreement from two sources"
            if field != "cover" and len(ranked_groups) > 1:
                runner_up = max(ranked_groups[1], key=lambda item: item.confidence)
                if abs(selected.confidence - runner_up.confidence) <= 0.015:
                    action = "review"
                    reason = "similarly ranked sources or editions disagree"

            decisions.append(
                MetadataDecision(
                    field=field,
                    old_value=old_value,
                    new_value=new_value,
                    action=action,
                    confidence=confidence,
                    evidence_ids=[item.id for item in selected_group],
                    reason=reason,
                )
            )
        return MetadataResolution(decisions=decisions, model="deterministic-consensus-v1")


def _image_media_type(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


class OnlineCoverFetcher:
    _ALLOWED_HOST_SUFFIXES = (
        "books.google.com",
        "books.googleusercontent.com",
        "googleusercontent.com",
        "covers.openlibrary.org",
        "archive.org",
    )

    def __init__(self, config: OnlineEnrichmentConfig, cache_dir: Path) -> None:
        self.config = config
        self.cache_dir = cache_dir

    @classmethod
    def _validate_url(cls, url: str) -> None:
        parsed = urllib.parse.urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https":
            raise ValueError("cover URL must use HTTPS")
        if not any(hostname == suffix or hostname.endswith("." + suffix) for suffix in cls._ALLOWED_HOST_SUFFIXES):
            raise ValueError(f"cover host is not allowed: {hostname}")

    def __call__(self, report: MetadataReport) -> bytes | None:
        decision = next(
            (item for item in report.applied_decisions if item.field == "cover"),
            None,
        )
        if decision is None:
            return None
        url = str(decision.new_value).strip()
        self._validate_url(url)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        cache_path = self.cache_dir / f"cover-{digest}.bin"
        if cache_path.exists():
            data = cache_path.read_bytes()
            if _image_media_type(data):
                return data

        request = urllib.request.Request(
            url,
            headers={
                "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8",
                "User-Agent": self.config.user_agent,
            },
        )
        with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
            final_url = response.geturl()
            self._validate_url(final_url)
            data = response.read(self.config.max_cover_bytes + 1)
        if len(data) > self.config.max_cover_bytes:
            raise ValueError(f"cover exceeds {self.config.max_cover_bytes} bytes")
        if not _image_media_type(data):
            raise ValueError("cover response is not a supported image")
        temp_path = cache_path.with_suffix(".tmp")
        temp_path.write_bytes(data)
        temp_path.replace(cache_path)
        return data
