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
from .config import HermesConfig
from .diff import compare_for_update
from .inspect import inspect_epub, write_quality_report
from .models import BookJob, BookManifest, UpdateDecision, canonical_id_for, sha256_file
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

    if job.input_format == "txt":
        candidate = build_draft_from_txt(job, snapshot.raw_path, paths.draft_dir)
        output_epub = normalize_existing_epub(job, candidate, paths.normalized_dir)
    elif job.input_format == "epub":
        output_epub = normalize_existing_epub(job, snapshot.raw_path, paths.normalized_dir)
    else:
        raise ValueError(f"Unsupported input format for MVP: {job.input_format}")

    inspection = inspect_epub(output_epub)

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
    candidate_manifest = _manifest_from_inspection(
        job,
        snapshot.source_hash,
        output_epub,
        inspection,
        UpdateDecision.NEW_BOOK,
    )
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

    manifest = _manifest_from_inspection(job, snapshot.source_hash, output_epub, inspection, decision)
    manifest.asset_report = asset_report_data
    (paths.reports_dir / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")

    publish_report = WebDavPublisher(webdav_client).publish(
        job.webdav_target_path,
        output_epub,
        manifest,
        expected_old_epub_hash=expected_old_epub_hash,
        expected_old_manifest_hash=expected_old_manifest_hash,
    )
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
