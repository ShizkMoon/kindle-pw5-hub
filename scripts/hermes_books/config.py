from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .models import AssetMode


class MetadataEnrichmentMode(str, Enum):
    OFF = "off"
    REPORT_ONLY = "report-only"
    AGGRESSIVE = "aggressive"


class KOReaderMetadataLocation(str, Enum):
    BOOK_FOLDER = "book_folder"
    DOCSETTINGS = "docsettings"
    HASHDOCSETTINGS = "hashdocsettings"


class TextCleaningMode(str, Enum):
    OFF = "off"
    REPORT_ONLY = "report-only"


class TypographyMode(str, Enum):
    OFF = "off"
    AUDIT_ONLY = "audit-only"
    NORMALIZE = "normalize"


@dataclass(frozen=True)
class WebDavConfig:
    base_url: str = ""
    books_path: str = "/books"
    username_env: str = "WEBDAV_USERNAME"
    password_env: str = "WEBDAV_PASSWORD"


@dataclass(frozen=True)
class PipelineConfig:
    require_epubcheck: bool = True
    keep_runs: bool = True
    output_profile: str = "koreader"
    language: str = "zh"


@dataclass(frozen=True)
class TypographyConfig:
    mode: TypographyMode = TypographyMode.NORMALIZE
    profile: str = "koreader-literary"
    normalize_fixed_font_sizes: bool = True
    normalize_absolute_line_heights: bool = True
    normalize_inline_styles: bool = True
    require_profile_link: bool = True
    block_on_failure: bool = True


@dataclass(frozen=True)
class UpdatePolicyConfig:
    default: str = "append-safe"
    chapter_fingerprint_threshold: float = 0.98
    block_on_chapter_count_decrease: bool = True
    block_on_reordered_existing_chapters: bool = True


@dataclass(frozen=True)
class AssetEnrichmentConfig:
    mode: AssetMode = AssetMode.BALANCED
    auto_cover_min_confidence: float = 0.85
    auto_insert_illustration_min_confidence: float = 0.92
    require_source_url: bool = True
    preserve_original_images: bool = True


@dataclass(frozen=True)
class MetadataEnrichmentConfig:
    mode: MetadataEnrichmentMode = MetadataEnrichmentMode.AGGRESSIVE
    auto_apply_min_confidence: float = 0.86
    require_evidence_url: bool = True
    allow_single_source_fields: bool = True
    block_on_conflicting_identity: bool = True
    preserve_target_path: bool = True
    preserve_canonical_id: bool = True
    write_epub_metadata: bool = True
    write_cover: bool = True
    write_description: bool = True
    write_subjects: bool = True


@dataclass(frozen=True)
class OnlineEnrichmentConfig:
    enabled: bool = False
    sources: str = "google-books,open-library"
    timeout_seconds: float = 15.0
    max_results_per_source: int = 5
    cache_ttl_hours: int = 168
    min_identity_score: float = 0.82
    max_response_bytes: int = 5_000_000
    max_cover_bytes: int = 15_000_000
    google_books_api_key_env: str = "GOOGLE_BOOKS_API_KEY"
    user_agent: str = "kindle-pw5-hub/1.0"


@dataclass(frozen=True)
class KOReaderConfig:
    metadata_location: KOReaderMetadataLocation = KOReaderMetadataLocation.BOOK_FOLDER
    aggressive_metadata_requires_stable_path: bool = True
    hashdocsettings_policy: str = "block"


@dataclass(frozen=True)
class TextCleaningConfig:
    mode: TextCleaningMode = TextCleaningMode.REPORT_ONLY
    max_input_chars: int = 120000
    chars_per_token: float = 2.0
    max_estimated_cost_cny: float = 1.0
    light_model_cny_per_1k_tokens: float = 0.002
    selected_route: str = "rules-first-report-only"
    escalation_route: str = "manual-gpt-5.5-review"
    long_context_route: str = "manual-deepseek-long-context"
    enable_model_calls: bool = False


@dataclass(frozen=True)
class HermesConfig:
    webdav: WebDavConfig = WebDavConfig()
    pipeline: PipelineConfig = PipelineConfig()
    typography: TypographyConfig = TypographyConfig()
    update_policy: UpdatePolicyConfig = UpdatePolicyConfig()
    asset_enrichment: AssetEnrichmentConfig = AssetEnrichmentConfig()
    metadata_enrichment: MetadataEnrichmentConfig = MetadataEnrichmentConfig()
    online_enrichment: OnlineEnrichmentConfig = OnlineEnrichmentConfig()
    koreader: KOReaderConfig = KOReaderConfig()
    text_cleaning: TextCleaningConfig = TextCleaningConfig()

    @classmethod
    def load(cls, path: Path | None) -> "HermesConfig":
        if path is None or not path.exists():
            return cls()
        data = _parse_simple_yaml(path.read_text(encoding="utf-8"))
        webdav = WebDavConfig(**{**WebDavConfig().__dict__, **data.get("webdav", {})})
        pipeline = PipelineConfig(**{**PipelineConfig().__dict__, **data.get("pipeline", {})})
        typography_data: dict[str, Any] = {
            **TypographyConfig().__dict__,
            **data.get("typography", {}),
        }
        typography_data["mode"] = TypographyMode(typography_data["mode"])
        typography = TypographyConfig(**typography_data)
        if typography.profile != "koreader-literary":
            raise ValueError("typography.profile currently only supports 'koreader-literary'")
        update_policy = UpdatePolicyConfig(
            **{**UpdatePolicyConfig().__dict__, **data.get("update_policy", {})}
        )
        asset_data: dict[str, Any] = {
            **AssetEnrichmentConfig().__dict__,
            **data.get("asset_enrichment", {}),
        }
        asset_data["mode"] = AssetMode(asset_data["mode"])
        asset_enrichment = AssetEnrichmentConfig(**asset_data)
        metadata_data: dict[str, Any] = {
            **MetadataEnrichmentConfig().__dict__,
            **data.get("metadata_enrichment", {}),
        }
        metadata_data["mode"] = MetadataEnrichmentMode(metadata_data["mode"])
        metadata_enrichment = MetadataEnrichmentConfig(**metadata_data)
        online_enrichment = OnlineEnrichmentConfig(
            **{**OnlineEnrichmentConfig().__dict__, **data.get("online_enrichment", {})}
        )
        if online_enrichment.timeout_seconds <= 0:
            raise ValueError("online_enrichment.timeout_seconds must be positive")
        if online_enrichment.max_results_per_source <= 0:
            raise ValueError("online_enrichment.max_results_per_source must be positive")
        if online_enrichment.cache_ttl_hours < 0:
            raise ValueError("online_enrichment.cache_ttl_hours must not be negative")
        if online_enrichment.max_response_bytes <= 0 or online_enrichment.max_cover_bytes <= 0:
            raise ValueError("online_enrichment response limits must be positive")
        if not 0 <= online_enrichment.min_identity_score <= 1:
            raise ValueError("online_enrichment.min_identity_score must be between 0 and 1")
        koreader_data: dict[str, Any] = {
            **KOReaderConfig().__dict__,
            **data.get("koreader", {}),
        }
        koreader_data["metadata_location"] = KOReaderMetadataLocation(koreader_data["metadata_location"])
        koreader = KOReaderConfig(**koreader_data)
        if koreader.hashdocsettings_policy != "block":
            raise ValueError("koreader.hashdocsettings_policy currently only supports 'block'")
        cleaning_data: dict[str, Any] = {
            **TextCleaningConfig().__dict__,
            **data.get("text_cleaning", {}),
        }
        cleaning_data["mode"] = TextCleaningMode(cleaning_data["mode"])
        text_cleaning = TextCleaningConfig(**cleaning_data)
        return cls(
            webdav=webdav,
            pipeline=pipeline,
            typography=typography,
            update_policy=update_policy,
            asset_enrichment=asset_enrichment,
            metadata_enrichment=metadata_enrichment,
            online_enrichment=online_enrichment,
            koreader=koreader,
            text_cleaning=text_cleaning,
        )


def _strip_inline_comment(value: str) -> str:
    quote = ""
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote:
            escaped = True
            continue
        if char in {'"', "'"}:
            if not quote:
                quote = char
            elif quote == char:
                quote = ""
            continue
        if char == "#" and not quote and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value


def _parse_scalar(value: str) -> Any:
    value = _strip_inline_comment(value).strip().strip('"').strip("'")
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _parse_simple_yaml(raw: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    section = ""
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" ") and line.endswith(":"):
            section = line[:-1].strip()
            result[section] = {}
            continue
        if section and ":" in line:
            key, value = line.split(":", 1)
            result[section][key.strip()] = _parse_scalar(value)
    return result
