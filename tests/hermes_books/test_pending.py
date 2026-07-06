import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.hermes_books.models import BookManifest, UpdateDecision
from scripts.hermes_books.pending import (
    approve_pending_report,
    list_pending_reports,
    reject_pending_report,
)
from scripts.hermes_books.publish import LocalWebDavClient, WebDavPublisher


def manifest(decision=UpdateDecision.BLOCKED_RISKY):
    return BookManifest(
        canonical_id="book::author",
        title="Book",
        author="Author",
        opf_identifier="urn:test:book-author",
        source_hash="source",
        output_hash="output",
        update_decision=decision,
    )


def write_publish_report(runs_root: Path, report: dict[str, str]) -> Path:
    reports_dir = runs_root / "job-1" / "reports"
    reports_dir.mkdir(parents=True)
    path = reports_dir / "publish-report.json"
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return path


class PendingTests(unittest.TestCase):
    def test_list_pending_reports_reads_run_publish_reports(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            epub = root / "candidate.epub"
            epub.write_bytes(b"candidate")
            report = WebDavPublisher(LocalWebDavClient(root / "webdav")).publish(
                "/books/Book - Author.epub",
                epub,
                manifest(),
            )
            write_publish_report(root / "runs", report)

            pending = list_pending_reports(root / "runs")

            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].candidate_hash, report["candidate_hash"])
            self.assertEqual(pending[0].pending_path, report["path"])

    def test_approve_pending_report_promotes_candidate_and_backs_up_old_live_book(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav_root = root / "webdav"
            (webdav_root / "books").mkdir(parents=True)
            live_epub = webdav_root / "books/Book - Author.epub"
            live_manifest = webdav_root / "books/Book - Author.hermes.json"
            live_epub.write_bytes(b"old epub")
            live_manifest.write_bytes(b'{"old": true}')
            epub = root / "candidate.epub"
            epub.write_bytes(b"candidate epub")
            report = WebDavPublisher(LocalWebDavClient(webdav_root)).publish(
                "/books/Book - Author.epub",
                epub,
                manifest(),
            )
            report_path = write_publish_report(root / "runs", report)

            approval = approve_pending_report(
                report_path,
                LocalWebDavClient(webdav_root, allow_existing_overwrite=True),
                confirm_hash=report["candidate_hash"],
                timestamp=lambda: "20260706T010203Z",
            )

            self.assertEqual(approval["status"], "approved")
            self.assertEqual(live_epub.read_bytes(), b"candidate epub")
            self.assertIn("book::author", live_manifest.read_text(encoding="utf-8"))
            backup_dir = webdav_root / "books/.backups/Book - Author/20260706T010203Z"
            self.assertEqual((backup_dir / "old.epub").read_bytes(), b"old epub")
            self.assertEqual((backup_dir / "old.hermes.json").read_bytes(), b'{"old": true}')

    def test_reject_pending_report_removes_candidate_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav_root = root / "webdav"
            epub = root / "candidate.epub"
            epub.write_bytes(b"candidate epub")
            report = WebDavPublisher(LocalWebDavClient(webdav_root)).publish(
                "/books/Book - Author.epub",
                epub,
                manifest(),
            )
            report_path = write_publish_report(root / "runs", report)
            pending_dir = webdav_root / report["path"].strip("/")

            rejection = reject_pending_report(
                report_path,
                LocalWebDavClient(webdav_root),
                confirm_hash=report["candidate_hash"],
            )

            self.assertEqual(rejection["status"], "rejected")
            self.assertFalse((pending_dir / "candidate.epub").exists())
            self.assertFalse((pending_dir / "candidate.hermes.json").exists())
            self.assertFalse((pending_dir / "risk-report.md").exists())

    def test_module_cli_help_exits_zero(self):
        repo_root = Path(__file__).resolve().parents[2]

        result = subprocess.run(
            [sys.executable, "-m", "scripts.hermes_books.pending", "--help"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Hermes pending update manager", result.stdout)


if __name__ == "__main__":
    unittest.main()
