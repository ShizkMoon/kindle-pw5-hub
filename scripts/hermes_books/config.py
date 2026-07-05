from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import AssetMode


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
class HermesConfig:
    webdav: WebDavConfig = WebDavConfig()
    pipeline: PipelineConfig = PipelineConfig()
    update_policy: UpdatePolicyConfig = UpdatePolicyConfig()
    asset_enrichment: AssetEnrichmentConfig = AssetEnrichmentConfig()

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
        return cls(webdav, pipeline, update_policy, asset_enrichment)


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
