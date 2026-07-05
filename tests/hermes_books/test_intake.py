import tempfile
import unittest
import json
from pathlib import Path

from scripts.hermes_books.config import AssetEnrichmentConfig, HermesConfig
from scripts.hermes_books.intake import EpubValidationResult, run_intake
from scripts.hermes_books.models import AssetMode, UpdateDecision
from scripts.hermes_books.publish import LocalWebDavClient
from tests.hermes_books.helpers import make_epub


def no_network_config() -> HermesConfig:
    return HermesConfig(asset_enrichment=AssetEnrichmentConfig(mode=AssetMode.OFF))


class IntakeTests(unittest.TestCase):
    def test_txt_input_generates_reports_and_publishes_new_book(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            txt = root / "novel.txt"
            txt.write_text("第一章\n正文\n", encoding="utf-8")

            result = run_intake(
                input_path=txt,
                title="小说",
                author="作者",
                runs_root=root / "runs",
                config=no_network_config(),
                webdav_client=LocalWebDavClient(root / "webdav"),
            )

            self.assertEqual(result.publish_report["status"], "published")
            self.assertTrue((root / "webdav/books/小说 - 作者.epub").exists())
            self.assertTrue((result.reports_dir / "quality-report.md").exists())
            self.assertTrue((result.reports_dir / "asset-report.json").exists())
            self.assertTrue((result.reports_dir / "epubcheck.json").exists())
            self.assertTrue((result.reports_dir / "publish-report.json").exists())

    def test_epub_input_uses_existing_epub_path_and_publishes_new_book(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_epub = make_epub(root / "source.epub")

            result = run_intake(
                input_path=source_epub,
                title="Book",
                author="Author",
                runs_root=root / "runs",
                config=no_network_config(),
                webdav_client=LocalWebDavClient(root / "webdav"),
            )

            self.assertEqual(result.publish_report["status"], "published")
            self.assertTrue((root / "webdav/books/Book - Author.epub").exists())

    def test_default_client_path_compares_existing_remote_update(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav = LocalWebDavClient(root / "webdav")
            old_epub = make_epub(
                root / "old.epub",
                chapters=[("第一章", "第一章正文")],
            )
            new_epub = make_epub(
                root / "new.epub",
                chapters=[("第一章", "第一章正文"), ("第二章", "第二章正文")],
            )

            run_intake(
                input_path=old_epub,
                title="Book",
                author="Author",
                runs_root=root / "old-runs",
                config=no_network_config(),
                webdav_client=webdav,
            )

            factory_calls = 0

            def webdav_client_factory(_config):
                nonlocal factory_calls
                factory_calls += 1
                return webdav

            result = run_intake(
                input_path=new_epub,
                title="Book",
                author="Author",
                runs_root=root / "new-runs",
                config=no_network_config(),
                webdav_client_factory=webdav_client_factory,
            )

            self.assertEqual(factory_calls, 1)
            self.assertTrue((result.reports_dir / "update-diff.md").exists())
            self.assertEqual(result.manifest.update_decision, UpdateDecision.SAFE_APPEND)

    def test_existing_remote_epub_without_manifest_goes_pending(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav = LocalWebDavClient(root / "webdav")
            old_epub = make_epub(root / "old.epub")
            new_epub = make_epub(root / "new.epub")

            run_intake(
                input_path=old_epub,
                title="Book",
                author="Author",
                runs_root=root / "old-runs",
                config=no_network_config(),
                webdav_client=webdav,
            )
            remote_epub = root / "webdav/books/Book - Author.epub"
            remote_manifest = root / "webdav/books/Book - Author.hermes.json"
            old_remote_bytes = remote_epub.read_bytes()
            remote_manifest.unlink()

            result = run_intake(
                input_path=new_epub,
                title="Book",
                author="Author",
                runs_root=root / "new-runs",
                config=no_network_config(),
                webdav_client=webdav,
            )

            self.assertEqual(result.publish_report["status"], "pending")
            self.assertEqual(remote_epub.read_bytes(), old_remote_bytes)
            update_diff = result.reports_dir / "update-diff.md"
            self.assertTrue(update_diff.exists())
            self.assertIn("remote target exists without Hermes manifest", update_diff.read_text(encoding="utf-8"))

    def test_existing_remote_opf_identifier_mismatch_goes_pending(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav = LocalWebDavClient(root / "webdav")
            old_epub = make_epub(root / "old.epub")
            new_epub = make_epub(root / "new.epub")

            run_intake(
                input_path=old_epub,
                title="Book",
                author="Author",
                runs_root=root / "old-runs",
                config=no_network_config(),
                webdav_client=webdav,
            )
            remote_epub = root / "webdav/books/Book - Author.epub"
            remote_manifest = root / "webdav/books/Book - Author.hermes.json"
            old_remote_bytes = remote_epub.read_bytes()
            manifest_data = json.loads(remote_manifest.read_text(encoding="utf-8"))
            manifest_data["opf_identifier"] = "urn:test:different-book"
            remote_manifest.write_text(json.dumps(manifest_data), encoding="utf-8")

            result = run_intake(
                input_path=new_epub,
                title="Book",
                author="Author",
                runs_root=root / "new-runs",
                config=no_network_config(),
                webdav_client=webdav,
            )

            self.assertEqual(result.publish_report["status"], "pending")
            self.assertEqual(remote_epub.read_bytes(), old_remote_bytes)
            update_diff = result.reports_dir / "update-diff.md"
            self.assertTrue(update_diff.exists())
            self.assertIn("OPF identifier mismatch for existing remote book", update_diff.read_text(encoding="utf-8"))

    def test_failing_injected_epub_validator_blocks_publish_and_writes_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_epub = make_epub(root / "source.epub")

            def failing_validator(_path):
                return EpubValidationResult(
                    status="failed",
                    errors=[{"id": "OPF-001", "message": "invalid package"}],
                    warnings=[],
                    checker="fake-epubcheck",
                )

            result = run_intake(
                input_path=source_epub,
                title="Book",
                author="Author",
                runs_root=root / "runs",
                config=no_network_config(),
                webdav_client=LocalWebDavClient(root / "webdav"),
                epub_validator=failing_validator,
            )

            self.assertEqual(result.publish_report["status"], "blocked")
            self.assertEqual(result.manifest.update_decision, UpdateDecision.BLOCKED_RISKY)
            self.assertFalse((root / "webdav/books/Book - Author.epub").exists())
            epubcheck = json.loads((result.reports_dir / "epubcheck.json").read_text(encoding="utf-8"))
            self.assertEqual(epubcheck["status"], "failed")
            self.assertEqual(epubcheck["errors"][0]["id"], "OPF-001")

    def test_existing_remote_actual_opf_identifier_mismatch_goes_pending(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav = LocalWebDavClient(root / "webdav")
            old_epub = make_epub(root / "old.epub", identifier="urn:test:book-author")
            stale_actual_epub = make_epub(root / "stale-actual.epub", identifier="urn:test:other-book")
            new_epub = make_epub(root / "new.epub", identifier="urn:test:book-author")

            run_intake(
                input_path=old_epub,
                title="Book",
                author="Author",
                runs_root=root / "old-runs",
                config=no_network_config(),
                webdav_client=webdav,
            )
            remote_epub = root / "webdav/books/Book - Author.epub"
            stale_remote_bytes = stale_actual_epub.read_bytes()
            remote_epub.write_bytes(stale_remote_bytes)

            result = run_intake(
                input_path=new_epub,
                title="Book",
                author="Author",
                runs_root=root / "new-runs",
                config=no_network_config(),
                webdav_client=webdav,
            )

            self.assertEqual(result.publish_report["status"], "pending")
            self.assertEqual(remote_epub.read_bytes(), stale_remote_bytes)
            update_diff = result.reports_dir / "update-diff.md"
            self.assertTrue(update_diff.exists())
            self.assertIn("OPF identifier mismatch for existing remote book", update_diff.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
