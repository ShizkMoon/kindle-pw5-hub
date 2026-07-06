from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import HermesConfig
from .publish import (
    ConditionalWriteFailed,
    ConditionalWriteUnsupported,
    HttpWebDavClient,
    LocalWebDavClient,
    WebDavClient,
    WebDavResource,
    WebDavWriteResult,
)


@dataclass(frozen=True)
class PendingReport:
    report_path: Path
    pending_path: str
    candidate_hash: str
    status: str
    reason: str = ""


@dataclass(frozen=True)
class _PendingPaths:
    slug: str
    pending_dir: str
    target_epub: str
    target_manifest: str
    candidate_epub: str
    candidate_manifest: str
    risk_report: str


def list_pending_reports(runs_root: Path) -> list[PendingReport]:
    pending: list[PendingReport] = []
    for report_path in sorted(runs_root.glob("*/reports/publish-report.json")):
        try:
            report = load_pending_report(report_path)
        except (ValueError, json.JSONDecodeError, OSError):
            continue
        pending.append(report)
    return pending


def load_pending_report(report_path: Path) -> PendingReport:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    status = str(data.get("status", ""))
    pending_path = str(data.get("path", ""))
    candidate_hash = str(data.get("candidate_hash", ""))
    if status != "pending" or not candidate_hash or "/.pending/" not in pending_path:
        raise ValueError(f"publish report is not a remote pending candidate: {report_path}")
    return PendingReport(
        report_path=report_path,
        pending_path=_normalise_posix_path(pending_path),
        candidate_hash=candidate_hash,
        status=status,
        reason=str(data.get("reason", "")),
    )


def approve_pending_report(
    report_path: Path,
    client: WebDavClient,
    *,
    confirm_hash: str,
    timestamp: Callable[[], str] | None = None,
) -> dict[str, str]:
    report = load_pending_report(report_path)
    _verify_confirmation(report, confirm_hash)
    paths = _pending_paths(report)
    candidate_epub = client.get(paths.candidate_epub)
    candidate_manifest = client.get(paths.candidate_manifest)
    actual_hash = hashlib.sha256(candidate_epub).hexdigest()
    if actual_hash != report.candidate_hash:
        raise ValueError("pending candidate hash does not match publish report")

    target_state = client.stat(paths.target_epub)
    manifest_state = client.stat(paths.target_manifest)
    old_epub = client.get(paths.target_epub) if target_state.exists else None
    old_manifest = client.get(paths.target_manifest) if manifest_state.exists else None
    if target_state.exists:
        _write_backup(client, paths, old_epub or b"", old_manifest, timestamp or _utc_timestamp)

    manifest_write = _write_live(client, paths.target_manifest, candidate_manifest, manifest_state)
    try:
        _write_live(client, paths.target_epub, candidate_epub, target_state)
    except Exception:
        _restore_live(client, paths.target_manifest, old_manifest, manifest_write)
        raise

    _delete_pending_files(client, paths)
    return {"status": "approved", "path": paths.target_epub, "candidate_hash": report.candidate_hash}


def reject_pending_report(
    report_path: Path,
    client: WebDavClient,
    *,
    confirm_hash: str,
) -> dict[str, str]:
    report = load_pending_report(report_path)
    _verify_confirmation(report, confirm_hash)
    paths = _pending_paths(report)
    _delete_pending_files(client, paths)
    return {"status": "rejected", "path": report.pending_path, "candidate_hash": report.candidate_hash}


def show_pending_report(report_path: Path, client: WebDavClient | None = None) -> dict[str, str]:
    report = load_pending_report(report_path)
    data = {
        "status": report.status,
        "path": report.pending_path,
        "candidate_hash": report.candidate_hash,
    }
    if report.reason:
        data["reason"] = report.reason
    if client is not None:
        paths = _pending_paths(report)
        try:
            data["risk_report"] = client.get(paths.risk_report).decode("utf-8", errors="replace")
        except Exception as exc:
            data["risk_report_error"] = str(exc)
    return data


def _verify_confirmation(report: PendingReport, confirm_hash: str) -> None:
    if confirm_hash != report.candidate_hash:
        raise ValueError("confirmation hash does not match pending candidate")


def _normalise_posix_path(path: str) -> str:
    normalised = "/" + path.replace("\\", "/").strip("/")
    parts = [part for part in normalised.split("/") if part]
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"invalid pending path: {path!r}")
    return "/" + posixpath.join(*parts)


def _pending_paths(report: PendingReport) -> _PendingPaths:
    pending_dir = _normalise_posix_path(report.pending_path)
    parts = [part for part in pending_dir.strip("/").split("/") if part]
    try:
        pending_index = parts.index(".pending")
    except ValueError as exc:
        raise ValueError(f"pending path has no .pending segment: {pending_dir}") from exc
    if pending_index == 0 or len(parts) < pending_index + 3:
        raise ValueError(f"pending path is incomplete: {pending_dir}")
    slug = parts[pending_index + 1]
    books_dir = "/" + posixpath.join(*parts[:pending_index])
    target_epub = posixpath.join(books_dir, f"{slug}.epub")
    return _PendingPaths(
        slug=slug,
        pending_dir=pending_dir,
        target_epub=target_epub,
        target_manifest=target_epub[:-5] + ".hermes.json",
        candidate_epub=posixpath.join(pending_dir, "candidate.epub"),
        candidate_manifest=posixpath.join(pending_dir, "candidate.hermes.json"),
        risk_report=posixpath.join(pending_dir, "risk-report.md"),
    )


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_backup(
    client: WebDavClient,
    paths: _PendingPaths,
    old_epub: bytes,
    old_manifest: bytes | None,
    timestamp: Callable[[], str],
) -> None:
    backup_root = posixpath.join(posixpath.dirname(paths.target_epub), ".backups", paths.slug)
    base_name = timestamp()
    for suffix in range(1, 100):
        name = base_name if suffix == 1 else f"{base_name}-{suffix}"
        backup_dir = posixpath.join(backup_root, name)
        client.mkdir(backup_dir)
        try:
            client.put_if_absent(posixpath.join(backup_dir, "old.epub"), old_epub)
            if old_manifest is not None:
                client.put_if_absent(posixpath.join(backup_dir, "old.hermes.json"), old_manifest)
            return
        except ConditionalWriteFailed:
            continue
    raise ConditionalWriteFailed("could not reserve pending approval backup path")


def _write_live(
    client: WebDavClient,
    path: str,
    data: bytes,
    state: WebDavResource,
) -> WebDavWriteResult:
    if state.exists:
        if not state.etag:
            raise ConditionalWriteUnsupported(f"{path} has no ETag for approved overwrite")
        return client.put_if_match(path, data, state.etag)
    return client.put_if_absent(path, data)


def _restore_live(
    client: WebDavClient,
    path: str,
    old_data: bytes | None,
    write_result: WebDavWriteResult | None,
) -> None:
    try:
        state = client.stat(path)
        etag = state.etag or (write_result.etag if write_result else None)
        if old_data is None:
            if state.exists and etag:
                client.delete_if_match(path, etag)
        elif state.exists and etag:
            client.put_if_match(path, old_data, etag)
    except Exception:
        return


def _delete_pending_files(client: WebDavClient, paths: _PendingPaths) -> None:
    for path in [paths.risk_report, paths.candidate_manifest, paths.candidate_epub]:
        try:
            state = client.stat(path)
            if state.exists and state.etag:
                client.delete_if_match(path, state.etag)
        except Exception:
            continue


def _client_from_args(args: argparse.Namespace) -> WebDavClient | None:
    root = getattr(args, "webdav_root", None)
    if root:
        return LocalWebDavClient(Path(root), allow_existing_overwrite=True)
    config_path = getattr(args, "config", None)
    if not config_path:
        return None
    config = HermesConfig.load(Path(config_path))
    username = os.environ.get(config.webdav.username_env, "")
    password = os.environ.get(config.webdav.password_env, "")
    return HttpWebDavClient(config.webdav.base_url, username, password)


def main() -> None:
    parser = argparse.ArgumentParser(description="Hermes pending update manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List remote pending candidates from local run reports")
    list_parser.add_argument("--runs-root", default="runs")

    show_parser = subparsers.add_parser("show", help="Show one pending candidate")
    show_parser.add_argument("--report", required=True)
    show_parser.add_argument("--webdav-root")
    show_parser.add_argument("--config")

    approve_parser = subparsers.add_parser("approve", help="Promote a pending candidate to the live book path")
    approve_parser.add_argument("--report", required=True)
    approve_parser.add_argument("--confirm", required=True)
    approve_parser.add_argument("--webdav-root")
    approve_parser.add_argument("--config", default="config/hermes-books.yaml")

    reject_parser = subparsers.add_parser("reject", help="Delete a pending candidate after review")
    reject_parser.add_argument("--report", required=True)
    reject_parser.add_argument("--confirm", required=True)
    reject_parser.add_argument("--webdav-root")
    reject_parser.add_argument("--config", default="config/hermes-books.yaml")

    args = parser.parse_args()
    if args.command == "list":
        payload = [
            {
                "report_path": str(report.report_path),
                "pending_path": report.pending_path,
                "candidate_hash": report.candidate_hash,
                "status": report.status,
                "reason": report.reason,
            }
            for report in list_pending_reports(Path(args.runs_root))
        ]
    elif args.command == "show":
        payload = show_pending_report(Path(args.report), _client_from_args(args))
    elif args.command == "approve":
        client = _client_from_args(args)
        if client is None:
            raise SystemExit("--webdav-root or --config is required")
        payload = approve_pending_report(Path(args.report), client, confirm_hash=args.confirm)
    else:
        client = _client_from_args(args)
        if client is None:
            raise SystemExit("--webdav-root or --config is required")
        payload = reject_pending_report(Path(args.report), client, confirm_hash=args.confirm)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
