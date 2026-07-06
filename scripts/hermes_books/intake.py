from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .assets import AssetEnricher, AssetFetcher, AssetProvider, apply_auto_adopted_assets
from .build import build_draft_from_txt, normalize_existing_epub
from .config import HermesConfig, MetadataEnrichmentMode
from .diff import compare_for_update
from .inspect import inspect_epub, write_quality_report
from .metadata import (
    MetadataClues,
    MetadataEnricher,
    MetadataProvider,
    MetadataReasoner,
    write_metadata_reports,
)
from .models import BookJob, BookManifest, UpdateDecision, canonical_id_for, sha256_file
from .opf_metadata import apply_metadata_to_epub
from .publish import HttpWebDavClient, WebDavClient, WebDavPublisher
from .sources import LocalFileSource, prepare_run_workspace


@dataclass
class IntakeResult:
    job: BookJob
    output_epub: Path
    manifest: BookManifest
    reports_dir: Path
    publish_report: dict[str, str]


@dataclass
class EpubValidationResult:
    status: str
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    checker: str = "epubcheck"
    infos: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def _manifest_from_inspection(
    job: BookJob,
    source_hash: str,
    output_epub: Path,
    inspection: Any,
    decision: UpdateDecision,
) -> BookManifest:
    canonical_id = canonical_id_for(job.title, job.author)
    return BookManifest(
        canonical_id=canonical_id,
        title=job.title,
        author=job.author,
        opf_identifier=inspection.opf_identifier or f"urn:hermes:{canonical_id}",
        source_hash=source_hash,
        output_hash=sha256_file(output_epub),
        update_decision=decision,
        chapter_map=[chapter.__dict__ for chapter in inspection.chapters],
        image_inventory=[image.__dict__ for image in inspection.images],
        quality_report={"issues": [issue.__dict__ for issue in inspection.issues]},
    )


def _failed_before_inspection_result(
    job: BookJob,
    source_hash: str,
    output_epub: Path,
    reports_dir: Path,
    error: Exception,
) -> IntakeResult:
    reason = f"intake failed before EPUB inspection: {error}"
    issue = {
        "severity": "HIGH",
        "code": "INTAKE_FAILED_BEFORE_INSPECTION",
        "message": reason,
        "href": str(output_epub),
    }
    canonical_id = canonical_id_for(job.title, job.author)
    output_hash = sha256_file(output_epub) if output_epub.exists() and output_epub.is_file() else ""
    manifest = BookManifest(
        canonical_id=canonical_id,
        title=job.title,
        author=job.author,
        opf_identifier=f"urn:hermes:{canonical_id}",
        source_hash=source_hash,
        output_hash=output_hash,
        update_decision=UpdateDecision.BLOCKED_RISKY,
        quality_report={"issues": [issue]},
    )
    publish_report = {
        "status": "blocked",
        "path": job.webdav_target_path,
        "reason": reason,
    }

    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "quality-report.md").write_text(
        "# EPUB quality report\n\n"
        f"Title: {job.title}\n"
        f"Author: {job.author}\n"
        "Chapters: 0\n"
        "Images: 0\n"
        "Missing cover: true\n"
        "\n"
        "## Issues\n"
        f"- [HIGH] INTAKE_FAILED_BEFORE_INSPECTION: {reason} {output_epub}\n",
        encoding="utf-8",
    )
    (reports_dir / "asset-report.json").write_text(
        json.dumps({"status": "skipped", "reason": reason}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    validation = EpubValidationResult(
        status="skipped",
        warnings=[{"id": "INTAKE_FAILED_BEFORE_INSPECTION", "message": reason}],
        checker="hermes-intake",
    )
    (reports_dir / "epubcheck.json").write_text(validation.to_json(), encoding="utf-8")
    (reports_dir / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    (reports_dir / "publish-report.json").write_text(
        json.dumps(publish_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return IntakeResult(job, output_epub, manifest, reports_dir, publish_report)


def _valid_books_path(path: str) -> str:
    normalised = "/" + path.replace("\\", "/").strip("/")
    parts = [part for part in normalised.split("/") if part]
    if not parts:
        raise ValueError("WebDAV books_path must not be empty")
    if any(part in {".", ".."} or ":" in part for part in parts):
        raise ValueError(f"WebDAV books_path must be a POSIX path: {path!r}")
    return posixpath.join("/", *parts)


def _manifest_path(target_epub_path: str) -> str:
    if not target_epub_path.endswith(".epub"):
        raise ValueError(f"Expected EPUB target path: {target_epub_path!r}")
    return target_epub_path[:-5] + ".hermes.json"


def _metadata_clues(job: BookJob, inspection: Any) -> MetadataClues:
    return MetadataClues(
        title=job.title,
        author=job.author,
        opf_identifier=getattr(inspection, "opf_identifier", ""),
        existing_metadata={
            "inspection_title": getattr(inspection, "title", ""),
            "inspection_author": getattr(inspection, "author", ""),
            "chapter_titles": [chapter.title for chapter in getattr(inspection, "chapters", [])[:20]],
            "missing_cover": getattr(inspection, "missing_cover", True),
        },
    )


def _run_metadata_enrichment(
    job: BookJob,
    output_epub: Path,
    inspection: Any,
    config: HermesConfig,
    reports_dir: Path,
    metadata_provider: MetadataProvider | None,
    metadata_reasoner: MetadataReasoner | None,
    metadata_cover_fetcher: Callable[[Any], bytes | None] | None,
) -> tuple[Path, Any, dict[str, Any]]:
    enricher = MetadataEnricher(config.metadata_enrichment)
    if config.metadata_enrichment.mode == MetadataEnrichmentMode.OFF:
        report = enricher.skipped("metadata enrichment disabled")
        write_metadata_reports(report, reports_dir)
        return output_epub, inspection, report.to_dict()
    if metadata_provider is None or metadata_reasoner is None:
        report = enricher.skipped("metadata provider or reasoner not configured")
        write_metadata_reports(report, reports_dir)
        return output_epub, inspection, report.to_dict()

    clues = _metadata_clues(job, inspection)
    try:
        evidence = metadata_provider.search(clues)
        resolution = metadata_reasoner.resolve(clues, evidence)
        report = enricher.decide(
            evidence,
            resolution,
            koreader_guard={
                "metadata_location": config.koreader.metadata_location.value,
                "stable_target_path": True,
                "stable_canonical_id": True,
                "live_publish_allowed": config.koreader.metadata_location.value != "hashdocsettings",
            },
        )
    except Exception as exc:
        report = enricher.skipped(f"metadata enrichment failed: {exc}")
        write_metadata_reports(report, reports_dir)
        return output_epub, inspection, report.to_dict()

    if report.applied_decisions and config.metadata_enrichment.write_epub_metadata:
        try:
            cover_bytes = None
            if (
                config.metadata_enrichment.write_cover
                and any(decision.field == "cover" for decision in report.applied_decisions)
                and metadata_cover_fetcher is not None
            ):
                cover_bytes = metadata_cover_fetcher(report)
            metadata_output = output_epub.with_name(f"{output_epub.stem}.metadata.epub")
            before_inspection = inspection
            output_epub = apply_metadata_to_epub(
                output_epub,
                metadata_output,
                report,
                cover_bytes=cover_bytes,
                write_cover=config.metadata_enrichment.write_cover,
                write_description=config.metadata_enrichment.write_description,
                write_subjects=config.metadata_enrichment.write_subjects,
            )
            inspection = inspect_epub(output_epub)
            structure_stable = _reader_structure_stable(before_inspection, inspection)
            report.koreader_guard["reader_structure_stable"] = structure_stable
            if not structure_stable:
                report.koreader_guard["live_publish_allowed"] = False
        except Exception as exc:
            report = enricher.skipped(f"metadata apply failed: {exc}")

    write_metadata_reports(report, reports_dir)
    return output_epub, inspection, report.to_dict()


def _reader_structure_stable(before: Any, after: Any) -> bool:
    before_chapters = getattr(before, "chapters", [])
    after_chapters = getattr(after, "chapters", [])
    if len(before_chapters) != len(after_chapters):
        return False
    for old, new in zip(before_chapters, after_chapters):
        if old.href != new.href or old.item_id != new.item_id:
            return False
        if old.fingerprint != new.fingerprint:
            return False
        if old.structure_fingerprint != new.structure_fingerprint:
            return False
        if old.resource_fingerprint != new.resource_fingerprint:
            return False
    return True


def _metadata_publish_guard_reason(
    config: HermesConfig,
    metadata_report: dict[str, Any],
    *,
    target_exists: bool,
) -> str | None:
    if metadata_report.get("status") != "applied":
        return None
    if not target_exists:
        return None
    if config.koreader.metadata_location.value == "hashdocsettings":
        return "KOReader hashdocsettings cannot preserve progress after EPUB content hash changes"
    guard = metadata_report.get("koreader_guard", {})
    if guard.get("stable_target_path") is False or guard.get("stable_canonical_id") is False:
        return "aggressive metadata changed path-sensitive identity"
    if guard.get("reader_structure_stable") is False:
        return "metadata rewrite changed reader-facing EPUB structure"
    return None


def _write_update_diff_report(
    path: Path,
    decision: UpdateDecision,
    reasons: list[str],
    matched_existing_chapters: int = 0,
    old_chapter_count: int = 0,
    new_chapter_count: int = 0,
) -> None:
    path.write_text(
        "# Update diff\n\n"
        f"Decision: {decision.value}\n"
        f"Reasons: {', '.join(reasons)}\n"
        f"Matched existing chapters: {matched_existing_chapters}\n"
        f"Old chapter count: {old_chapter_count}\n"
        f"New chapter count: {new_chapter_count}\n",
        encoding="utf-8",
    )


def _default_epub_validator(epub_path: Path) -> EpubValidationResult:
    try:
        from scripts.epub_fix import validate as epubcheck_validate
    except Exception as exc:
        return EpubValidationResult(
            status="skipped",
            warnings=[{"id": "EPUBCHECK_UNAVAILABLE", "message": f"EPUBCheck helper unavailable: {exc}"}],
        )

    java_path = epubcheck_validate.find_java()
    if not java_path:
        return EpubValidationResult(
            status="skipped",
            warnings=[{"id": "JAVA_UNAVAILABLE", "message": "Java runtime not found; EPUBCheck skipped"}],
        )

    script_dir = str(Path(epubcheck_validate.__file__).resolve().parent)
    jar_path = epubcheck_validate.find_epubcheck_jar(script_dir)
    if not jar_path:
        return EpubValidationResult(
            status="skipped",
            warnings=[{"id": "EPUBCHECK_JAR_UNAVAILABLE", "message": "epubcheck.jar not found; validation skipped"}],
        )

    checker = f"epubcheck:{jar_path}"
    try:
        result = subprocess.run(
            [java_path, "-jar", jar_path, "--json", str(epub_path.resolve())],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return EpubValidationResult(
            status="failed",
            errors=[{"id": "EPUBCHECK_TIMEOUT", "message": "EPUBCheck timed out after 300 seconds"}],
            checker=checker,
        )
    except Exception as exc:
        return EpubValidationResult(
            status="failed",
            errors=[{"id": "EPUBCHECK_RUN_FAILED", "message": f"EPUBCheck failed to run: {exc}"}],
            checker=checker,
        )

    raw_output = result.stdout.strip()
    if not raw_output:
        message = result.stderr.strip() or "EPUBCheck produced no JSON output"
        return EpubValidationResult(
            status="failed",
            errors=[{"id": "EPUBCHECK_NO_OUTPUT", "message": message[:2000]}],
            checker=checker,
        )

    try:
        errors, warnings, infos = epubcheck_validate.parse_epubcheck_output(raw_output)
    except (json.JSONDecodeError, ValueError) as exc:
        return EpubValidationResult(
            status="failed",
            errors=[{"id": "EPUBCHECK_PARSE_FAILED", "message": f"Could not parse EPUBCheck JSON: {exc}"}],
            checker=checker,
        )

    status = "failed" if errors else "passed"
    return EpubValidationResult(status=status, errors=errors, warnings=warnings, infos=infos, checker=checker)


def run_intake(
    input_path: Path,
    title: str,
    author: str,
    runs_root: Path = Path("runs"),
    config: HermesConfig | None = None,
    webdav_client: WebDavClient | None = None,
    *,
    webdav_client_factory: Callable[[HermesConfig], WebDavClient] | None = None,
    epub_validator: Callable[[Path], EpubValidationResult] | None = None,
    asset_provider: AssetProvider | None = None,
    asset_fetcher: AssetFetcher | None = None,
    metadata_provider: MetadataProvider | None = None,
    metadata_reasoner: MetadataReasoner | None = None,
    metadata_cover_fetcher: Callable[[Any], bytes | None] | None = None,
) -> IntakeResult:
    config = config or HermesConfig.load(None)
    books_path = _valid_books_path(config.webdav.books_path)
    job = BookJob.from_input(
        input_path,
        title,
        author,
        runs_root,
        config.asset_enrichment.mode,
        books_path,
    )
    paths = prepare_run_workspace(job)
    snapshot = LocalFileSource(job).snapshot()

    output_epub = snapshot.raw_path
    try:
        if job.input_format == "txt":
            candidate = build_draft_from_txt(job, snapshot.raw_path, paths.draft_dir)
            output_epub = normalize_existing_epub(job, candidate, paths.normalized_dir)
        elif job.input_format == "epub":
            output_epub = normalize_existing_epub(job, snapshot.raw_path, paths.normalized_dir)
        else:
            raise ValueError(f"Unsupported input format for MVP: {job.input_format}")

        inspection = inspect_epub(output_epub)
    except Exception as exc:
        return _failed_before_inspection_result(
            job,
            snapshot.source_hash,
            output_epub,
            paths.reports_dir,
            exc,
        )

    output_epub, inspection, metadata_report_data = _run_metadata_enrichment(
        job,
        output_epub,
        inspection,
        config,
        paths.reports_dir,
        metadata_provider,
        metadata_reasoner,
        metadata_cover_fetcher,
    )

    asset_cache_dir = job.run_dir / "assets-cache"
    asset_report = AssetEnricher(config.asset_enrichment, asset_provider).plan(
        title,
        author,
        inspection,
        asset_cache_dir,
    )
    if apply_auto_adopted_assets(output_epub, asset_report, asset_cache_dir, asset_fetcher):
        inspection = inspect_epub(output_epub)

    write_quality_report(inspection, paths.reports_dir / "quality-report.md")
    asset_report_data = json.loads(asset_report.to_json())
    (paths.reports_dir / "asset-report.json").write_text(
        json.dumps(asset_report_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    validation = (epub_validator or _default_epub_validator)(output_epub)
    (paths.reports_dir / "epubcheck.json").write_text(validation.to_json(), encoding="utf-8")

    if config.pipeline.require_epubcheck and validation.status != "passed":
        decision = UpdateDecision.BLOCKED_RISKY
        manifest = _manifest_from_inspection(job, snapshot.source_hash, output_epub, inspection, decision)
        manifest.metadata_report = metadata_report_data
        manifest.asset_report = asset_report_data
        (paths.reports_dir / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
        reason = f"EPUBCheck validation status {validation.status}"
        publish_report = {
            "status": "blocked",
            "path": job.webdav_target_path,
            "reason": reason,
        }
        (paths.reports_dir / "publish-report.json").write_text(
            json.dumps(publish_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return IntakeResult(job, output_epub, manifest, paths.reports_dir, publish_report)

    if webdav_client is None:
        if webdav_client_factory is not None:
            webdav_client = webdav_client_factory(config)
        else:
            username = os.environ.get(config.webdav.username_env, "")
            password = os.environ.get(config.webdav.password_env, "")
            webdav_client = HttpWebDavClient(config.webdav.base_url, username, password)

    decision = UpdateDecision.NEW_BOOK
    manifest_path = _manifest_path(job.webdav_target_path)
    try:
        target_exists = webdav_client.exists(job.webdav_target_path)
        manifest_exists = webdav_client.exists(manifest_path)
    except Exception:
        decision = UpdateDecision.BLOCKED_RISKY
        _write_update_diff_report(
            paths.reports_dir / "update-diff.md",
            decision,
            ["remote target state unavailable"],
        )
        manifest = _manifest_from_inspection(job, snapshot.source_hash, output_epub, inspection, decision)
        manifest.metadata_report = metadata_report_data
        manifest.asset_report = asset_report_data
        (paths.reports_dir / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
        publish_report = {
            "status": "pending",
            "path": job.webdav_target_path,
            "reason": "remote target state unavailable",
        }
        (paths.reports_dir / "publish-report.json").write_text(
            json.dumps(publish_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return IntakeResult(job, output_epub, manifest, paths.reports_dir, publish_report)

    expected_old_epub_hash: str | None = None
    expected_old_manifest_hash: str | None = None
    metadata_guard_reason: str | None = None
    candidate_manifest = _manifest_from_inspection(
        job,
        snapshot.source_hash,
        output_epub,
        inspection,
        UpdateDecision.NEW_BOOK,
    )
    candidate_manifest.metadata_report = metadata_report_data
    if target_exists and not manifest_exists:
        decision = UpdateDecision.BLOCKED_RISKY
        _write_update_diff_report(
            paths.reports_dir / "update-diff.md",
            decision,
            ["remote target exists without Hermes manifest"],
        )
    elif target_exists and manifest_exists:
        try:
            old_manifest_bytes = webdav_client.get(manifest_path)
            old_manifest = BookManifest.from_json(old_manifest_bytes.decode("utf-8"))
        except Exception:
            decision = UpdateDecision.BLOCKED_RISKY
            _write_update_diff_report(
                paths.reports_dir / "update-diff.md",
                decision,
                ["remote Hermes manifest unreadable"],
            )
        else:
            old_epub = paths.raw_dir / "old-remote.epub"
            try:
                old_epub_bytes = webdav_client.get(job.webdav_target_path)
                expected_old_manifest_hash = hashlib.sha256(old_manifest_bytes).hexdigest()
                expected_old_epub_hash = hashlib.sha256(old_epub_bytes).hexdigest()
                old_epub.write_bytes(old_epub_bytes)
                old_inspection = inspect_epub(old_epub)
            except Exception as exc:
                decision = UpdateDecision.BLOCKED_RISKY
                _write_update_diff_report(
                    paths.reports_dir / "update-diff.md",
                    decision,
                    [f"remote EPUB unreadable: {exc}"],
                )
            else:
                diff = compare_for_update(
                    old_manifest,
                    candidate_manifest,
                    old_inspection,
                    inspection,
                    config.update_policy.chapter_fingerprint_threshold,
                )
                decision = diff.decision
                reasons = list(diff.reasons)
                identifiers = {
                    old_manifest.opf_identifier,
                    old_inspection.opf_identifier,
                    candidate_manifest.opf_identifier,
                }
                if len(identifiers) != 1:
                    decision = UpdateDecision.BLOCKED_RISKY
                    reasons.append("OPF identifier mismatch for existing remote book")
                _write_update_diff_report(
                    paths.reports_dir / "update-diff.md",
                    decision,
                    reasons,
                    diff.matched_existing_chapters,
                    diff.old_chapter_count,
                    diff.new_chapter_count,
                )

    metadata_guard_reason = _metadata_publish_guard_reason(
        config,
        metadata_report_data,
        target_exists=target_exists,
    )
    if metadata_guard_reason is not None:
        decision = UpdateDecision.BLOCKED_RISKY
        _write_update_diff_report(
            paths.reports_dir / "update-diff.md",
            decision,
            [metadata_guard_reason],
        )

    manifest = _manifest_from_inspection(job, snapshot.source_hash, output_epub, inspection, decision)
    manifest.metadata_report = metadata_report_data
    manifest.asset_report = asset_report_data
    (paths.reports_dir / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")

    try:
        publish_report = WebDavPublisher(webdav_client).publish(
            job.webdav_target_path,
            output_epub,
            manifest,
            expected_old_epub_hash=expected_old_epub_hash,
            expected_old_manifest_hash=expected_old_manifest_hash,
        )
    except Exception as exc:
        publish_report = {
            "status": "pending-local",
            "path": job.webdav_target_path,
            "reason": f"publish failed: {exc}",
        }
    if metadata_guard_reason and "reason" not in publish_report:
        publish_report["reason"] = metadata_guard_reason
    (paths.reports_dir / "publish-report.json").write_text(
        json.dumps(publish_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return IntakeResult(job, output_epub, manifest, paths.reports_dir, publish_report)


def main() -> None:
    parser = argparse.ArgumentParser(description="Hermes local TXT/EPUB intake")
    parser.add_argument("input", help="Local TXT or EPUB input path")
    parser.add_argument("-t", "--title", required=True)
    parser.add_argument("-a", "--author", required=True)
    parser.add_argument("--config", default="config/hermes-books.yaml")
    parser.add_argument("--runs-root", default="runs")
    args = parser.parse_args()

    config = HermesConfig.load(Path(args.config))
    result = run_intake(Path(args.input), args.title, args.author, Path(args.runs_root), config)
    print(
        json.dumps(
            {
                "job_id": result.job.id,
                "output_epub": str(result.output_epub),
                "manifest": str(result.reports_dir / "manifest.json"),
                "publish": result.publish_report,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
