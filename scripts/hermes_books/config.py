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
    update_policy: UpdatePolicyConfig = UpdatePolicyConfig()
    asset_enrichment: AssetEnrichmentConfig = AssetEnrichmentConfig()
    metadata_enrichment: MetadataEnrichmentConfig = MetadataEnrichmentConfig()
    koreader: KOReaderConfig = KOReaderConfig()
    text_cleaning: TextCleaningConfig = TextCleaningConfig()

    @classmethod
    def load(cls, path: Path | None) -> "HermesConfig":
        if path is None or not path.exists():
            return cls()
        data = _parse_simple_yaml(path.read_text(encoding="utf-8"))
        webdav = WebDavConfig(**{**WebDavConfig().__dict__, **data.get("webdav", {})})
        pipeline = PipelineConfig(**{**PipelineConfig().__dict__, **data.get("pipeline", {})})
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
            webdav,
            pipeline,
            update_policy,
            asset_enrichment,
            metadata_enrichment,
            koreader,
            text_cleaning,
        )


def _parse_scalar(value: str) -> Any:
    value = value.strip().strip('"').strip("'")
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
