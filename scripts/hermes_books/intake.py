from __future__ import annotations

import argparse
import json
import os
import posixpath
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .assets import AssetEnricher
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


def run_intake(
    input_path: Path,
    title: str,
    author: str,
    runs_root: Path = Path("runs"),
    config: HermesConfig | None = None,
    webdav_client: WebDavClient | None = None,
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
    write_quality_report(inspection, paths.reports_dir / "quality-report.md")

    asset_report = AssetEnricher(config.asset_enrichment).plan(
        title,
        author,
        inspection,
        job.run_dir / "assets-cache",
    )
    asset_report_data = json.loads(asset_report.to_json())
    (paths.reports_dir / "asset-report.json").write_text(
        json.dumps(asset_report_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    decision = UpdateDecision.NEW_BOOK
    manifest_path = _manifest_path(job.webdav_target_path)
    if (
        webdav_client is not None
        and webdav_client.exists(manifest_path)
        and webdav_client.exists(job.webdav_target_path)
    ):
        old_manifest = BookManifest.from_json(webdav_client.get(manifest_path).decode("utf-8"))
        old_epub = paths.raw_dir / "old-remote.epub"
        old_epub.write_bytes(webdav_client.get(job.webdav_target_path))
        old_inspection = inspect_epub(old_epub)
        candidate_manifest = _manifest_from_inspection(
            job,
            snapshot.source_hash,
            output_epub,
            inspection,
            UpdateDecision.NEW_BOOK,
        )
        diff = compare_for_update(
            old_manifest,
            candidate_manifest,
            old_inspection,
            inspection,
            config.update_policy.chapter_fingerprint_threshold,
        )
        decision = diff.decision
        (paths.reports_dir / "update-diff.md").write_text(
            "# Update diff\n\n"
            f"Decision: {diff.decision.value}\n"
            f"Reasons: {', '.join(diff.reasons)}\n"
            f"Matched existing chapters: {diff.matched_existing_chapters}\n"
            f"Old chapter count: {diff.old_chapter_count}\n"
            f"New chapter count: {diff.new_chapter_count}\n",
            encoding="utf-8",
        )

    manifest = _manifest_from_inspection(job, snapshot.source_hash, output_epub, inspection, decision)
    manifest.asset_report = asset_report_data
    (paths.reports_dir / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")

    if webdav_client is None:
        username = os.environ.get(config.webdav.username_env, "")
        password = os.environ.get(config.webdav.password_env, "")
        webdav_client = HttpWebDavClient(config.webdav.base_url, username, password)
    publish_report = WebDavPublisher(webdav_client).publish(job.webdav_target_path, output_epub, manifest)
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
