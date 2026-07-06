import tempfile
import unittest
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from scripts.hermes_books.assets import AssetCandidate
from scripts.hermes_books.config import (
    AssetEnrichmentConfig,
    HermesConfig,
    KOReaderConfig,
    KOReaderMetadataLocation,
    PipelineConfig,
)
from scripts.hermes_books.inspect import inspect_epub
from scripts.hermes_books.intake import EpubValidationResult, run_intake
from scripts.hermes_books.metadata import MetadataDecision, MetadataEvidence, MetadataResolution
from scripts.hermes_books.models import AssetMode, UpdateDecision
from scripts.hermes_books.publish import LocalWebDavClient
from tests.hermes_books.helpers import make_epub


def no_network_config() -> HermesConfig:
    return HermesConfig(
        asset_enrichment=AssetEnrichmentConfig(mode=AssetMode.OFF),
        pipeline=PipelineConfig(require_epubcheck=False),
    )


def required_epubcheck_config() -> HermesConfig:
    return HermesConfig(
        asset_enrichment=AssetEnrichmentConfig(mode=AssetMode.OFF),
        pipeline=PipelineConfig(require_epubcheck=True),
    )


class StaticMetadataProvider:
    def search(self, _clues):
        return [
            MetadataEvidence(
                "store-1",
                "store",
                "https://example.test/books/1",
                {"title": "标准书名", "illustrators": ["画师"]},
            )
        ]


class StaticMetadataReasoner:
    def resolve(self, _clues, _evidence):
        return MetadataResolution(
            decisions=[
                MetadataDecision("title", "Book", "标准书名", "apply", 0.96, ["store-1"], "title match"),
                MetadataDecision("illustrators", [], ["画师"], "apply", 0.96, ["store-1"], "illustrator match"),
            ]
        )


def pending_candidate_path(webdav_root: Path, report: dict[str, str]) -> Path:
    return webdav_root / report["path"].strip("/") / "candidate.epub"


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

    def test_aggressive_metadata_enrichment_writes_reports_manifest_and_epub(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_epub = make_epub(root / "source.epub", title="Old Title")

            class StaticReasoner:
                def resolve(self, _clues, _evidence):
                    return MetadataResolution(
                        decisions=[
                            MetadataDecision("title", "Old Title", "标准书名", "apply", 0.96, ["store-1"], "title match"),
                            MetadataDecision("illustrators", [], ["画师"], "apply", 0.96, ["store-1"], "illustrator match"),
                            MetadataDecision("isbn", "", "9780000000000", "apply", 0.96, ["store-1"], "isbn match"),
                        ]
                    )

            result = run_intake(
                input_path=source_epub,
                title="Book",
                author="Author",
                runs_root=root / "runs",
                config=no_network_config(),
                webdav_client=LocalWebDavClient(root / "webdav"),
                metadata_provider=StaticMetadataProvider(),
                metadata_reasoner=StaticReasoner(),
            )

            self.assertEqual(result.publish_report["status"], "published")
            metadata_json = json.loads((result.reports_dir / "metadata-report.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata_json["status"], "applied")
            self.assertEqual(result.manifest.metadata_report["status"], "applied")
            self.assertTrue((result.reports_dir / "metadata-report.md").exists())
            published = root / "webdav/books/Book - Author.epub"
            with zipfile.ZipFile(published) as archive:
                opf_text = archive.read("EPUB/content.opf").decode("utf-8")
            self.assertIn("标准书名", opf_text)
            self.assertIn("画师", opf_text)
            self.assertIn("9780000000000", opf_text)

    def test_existing_book_aggressive_metadata_book_folder_allows_safe_metadata_publish(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav_root = root / "webdav"
            client = LocalWebDavClient(webdav_root, allow_existing_overwrite=True)
            old_epub = make_epub(root / "old.epub", title="Book")
            new_epub = make_epub(root / "new.epub", title="Book")

            run_intake(
                input_path=old_epub,
                title="Book",
                author="Author",
                runs_root=root / "old-runs",
                config=no_network_config(),
                webdav_client=client,
            )
            result = run_intake(
                input_path=new_epub,
                title="Book",
                author="Author",
                runs_root=root / "new-runs",
                config=no_network_config(),
                webdav_client=client,
                metadata_provider=StaticMetadataProvider(),
                metadata_reasoner=StaticMetadataReasoner(),
            )

            self.assertEqual(result.publish_report["status"], "published")
            self.assertEqual(result.manifest.update_decision, UpdateDecision.SAFE_METADATA)
            with zipfile.ZipFile(webdav_root / "books/Book - Author.epub") as archive:
                opf_text = archive.read("EPUB/content.opf").decode("utf-8")
            self.assertIn("标准书名", opf_text)

    def test_existing_book_aggressive_metadata_hashdocsettings_goes_pending(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav_root = root / "webdav"
            old_epub = make_epub(root / "old.epub", title="Book")
            new_epub = make_epub(root / "new.epub", title="Book")
            config = HermesConfig(
                asset_enrichment=AssetEnrichmentConfig(mode=AssetMode.OFF),
                pipeline=PipelineConfig(require_epubcheck=False),
                koreader=KOReaderConfig(metadata_location=KOReaderMetadataLocation.HASHDOCSETTINGS),
            )

            run_intake(
                input_path=old_epub,
                title="Book",
                author="Author",
                runs_root=root / "old-runs",
                config=config,
                webdav_client=LocalWebDavClient(webdav_root, allow_existing_overwrite=True),
            )
            remote_epub = webdav_root / "books/Book - Author.epub"
            old_remote_bytes = remote_epub.read_bytes()

            result = run_intake(
                input_path=new_epub,
                title="Book",
                author="Author",
                runs_root=root / "new-runs",
                config=config,
                webdav_client=LocalWebDavClient(webdav_root, allow_existing_overwrite=True),
                metadata_provider=StaticMetadataProvider(),
                metadata_reasoner=StaticMetadataReasoner(),
            )

            self.assertEqual(result.publish_report["status"], "pending")
            self.assertEqual(result.manifest.update_decision, UpdateDecision.BLOCKED_RISKY)
            self.assertIn("hashdocsettings", result.publish_report["reason"])
            self.assertEqual(remote_epub.read_bytes(), old_remote_bytes)

    def test_unreadable_source_epub_writes_local_failure_reports_without_publishing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_epub = root / "broken.epub"
            source_epub.write_bytes(b"not an epub archive")

            result = run_intake(
                input_path=source_epub,
                title="Book",
                author="Author",
                runs_root=root / "runs",
                config=no_network_config(),
                webdav_client=LocalWebDavClient(root / "webdav"),
            )

            self.assertEqual(result.publish_report["status"], "blocked")
            self.assertIn("intake failed before EPUB inspection", result.publish_report["reason"])
            self.assertEqual(result.manifest.update_decision, UpdateDecision.BLOCKED_RISKY)
            self.assertFalse((root / "webdav/books/Book - Author.epub").exists())
            self.assertTrue((result.reports_dir / "quality-report.md").exists())
            self.assertTrue((result.reports_dir / "manifest.json").exists())
            self.assertTrue((result.reports_dir / "publish-report.json").exists())

    def test_auto_adopted_cover_is_inserted_before_validation_and_publish(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_epub = make_epub(root / "source.epub")
            cover_path = root / "cover.jpg"
            cover_path.write_bytes(b"fake cover bytes")

            class LocalCoverProvider:
                def candidates(self, title: str, author: str, role: str):
                    return [
                        AssetCandidate(
                            role=role,
                            source_url="https://assets.example/cover.jpg",
                            local_path=cover_path,
                            width=1600,
                            height=2400,
                            confidence=0.95,
                            reason="local high confidence cover",
                        )
                    ]

            validation_seen = {}

            def validator(path):
                validation_seen["missing_cover"] = inspect_epub(path).missing_cover
                return EpubValidationResult(status="passed")

            result = run_intake(
                input_path=source_epub,
                title="Book",
                author="Author",
                runs_root=root / "runs",
                config=HermesConfig(
                    asset_enrichment=AssetEnrichmentConfig(mode=AssetMode.BALANCED),
                    pipeline=PipelineConfig(require_epubcheck=False),
                ),
                webdav_client=LocalWebDavClient(root / "webdav"),
                epub_validator=validator,
                asset_provider=LocalCoverProvider(),
            )

            published_epub = root / "webdav/books/Book - Author.epub"
            self.assertEqual(result.publish_report["status"], "published")
            self.assertFalse(validation_seen["missing_cover"])
            self.assertFalse(inspect_epub(result.output_epub).missing_cover)
            self.assertFalse(inspect_epub(published_epub).missing_cover)

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

    def test_existing_remote_mutated_after_diff_goes_pending_without_overwriting_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav_root = root / "webdav"
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
                webdav_client=LocalWebDavClient(webdav_root),
            )
            remote_epub = webdav_root / "books/Book - Author.epub"
            mutated_remote_bytes = b"changed after append-safe diff"

            class MutatingAfterDiffReadClient(LocalWebDavClient):
                def __init__(self, client_root):
                    super().__init__(client_root)
                    self.mutated = False

                def get(self, path):
                    data = super().get(path)
                    if path == "/books/Book - Author.epub" and not self.mutated:
                        self.mutated = True
                        remote_epub.write_bytes(mutated_remote_bytes)
                    return data

            result = run_intake(
                input_path=new_epub,
                title="Book",
                author="Author",
                runs_root=root / "new-runs",
                config=no_network_config(),
                webdav_client=MutatingAfterDiffReadClient(webdav_root),
            )

            self.assertEqual(result.manifest.update_decision, UpdateDecision.SAFE_APPEND)
            self.assertEqual(result.publish_report["status"], "pending")
            self.assertEqual(remote_epub.read_bytes(), mutated_remote_bytes)
            self.assertNotEqual(remote_epub.read_bytes(), result.output_epub.read_bytes())
            self.assertTrue(pending_candidate_path(webdav_root, result.publish_report).exists())

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

    def test_remote_state_probe_failure_writes_local_reports_without_crashing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_epub = make_epub(root / "source.epub")

            class UnavailableRemoteClient(LocalWebDavClient):
                def exists(self, path):
                    raise RuntimeError("remote unavailable")

                def stat(self, path):
                    raise RuntimeError("remote unavailable")

                def put(self, path, data):
                    raise AssertionError("remote pending upload must not be attempted after state probe failure")

                def put_if_absent(self, path, data):
                    raise AssertionError("remote publish must not be attempted after state probe failure")

            result = run_intake(
                input_path=source_epub,
                title="Book",
                author="Author",
                runs_root=root / "runs",
                config=no_network_config(),
                webdav_client=UnavailableRemoteClient(root / "webdav"),
            )

            self.assertEqual(result.publish_report["status"], "pending")
            self.assertIn("remote target state unavailable", result.publish_report["reason"])
            self.assertEqual(result.manifest.update_decision, UpdateDecision.BLOCKED_RISKY)
            self.assertTrue((result.reports_dir / "manifest.json").exists())
            self.assertTrue((result.reports_dir / "publish-report.json").exists())
            self.assertTrue((result.reports_dir / "update-diff.md").exists())

    def test_pending_publish_failure_writes_local_report_without_crashing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav_root = root / "webdav"
            source_epub = make_epub(root / "source.epub")

            class PendingUploadFailsClient(LocalWebDavClient):
                def put_if_absent(self, path, data):
                    if "/.pending/" in path:
                        raise RuntimeError("pending upload failed")
                    return super().put_if_absent(path, data)

            client = PendingUploadFailsClient(webdav_root)
            run_intake(
                input_path=source_epub,
                title="Book",
                author="Author",
                runs_root=root / "old-runs",
                config=no_network_config(),
                webdav_client=client,
            )
            (webdav_root / "books/Book - Author.hermes.json").unlink()

            result = run_intake(
                input_path=source_epub,
                title="Book",
                author="Author",
                runs_root=root / "new-runs",
                config=no_network_config(),
                webdav_client=client,
            )

            self.assertEqual(result.publish_report["status"], "pending-local")
            self.assertIn("pending upload failed", result.publish_report["reason"])
            self.assertTrue((result.reports_dir / "publish-report.json").exists())

    def test_unreadable_existing_remote_manifest_goes_pending_without_touching_old_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav_root = root / "webdav"
            webdav = LocalWebDavClient(webdav_root)
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
            remote_epub = webdav_root / "books/Book - Author.epub"
            old_remote_bytes = remote_epub.read_bytes()

            class UnreadableManifestClient(LocalWebDavClient):
                def get(self, path):
                    if path == "/books/Book - Author.hermes.json":
                        raise RuntimeError("injected manifest read failure")
                    return super().get(path)

            result = run_intake(
                input_path=new_epub,
                title="Book",
                author="Author",
                runs_root=root / "new-runs",
                config=no_network_config(),
                webdav_client=UnreadableManifestClient(webdav_root),
            )

            self.assertEqual(result.publish_report["status"], "pending")
            self.assertEqual(result.manifest.update_decision, UpdateDecision.BLOCKED_RISKY)
            self.assertEqual(remote_epub.read_bytes(), old_remote_bytes)
            update_diff = result.reports_dir / "update-diff.md"
            self.assertTrue(update_diff.exists())
            self.assertIn("remote Hermes manifest unreadable", update_diff.read_text(encoding="utf-8"))

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
                config=required_epubcheck_config(),
                webdav_client=LocalWebDavClient(root / "webdav"),
                epub_validator=failing_validator,
            )

            self.assertEqual(result.publish_report["status"], "blocked")
            self.assertEqual(result.manifest.update_decision, UpdateDecision.BLOCKED_RISKY)
            self.assertFalse((root / "webdav/books/Book - Author.epub").exists())
            epubcheck = json.loads((result.reports_dir / "epubcheck.json").read_text(encoding="utf-8"))
            self.assertEqual(epubcheck["status"], "failed")
            self.assertEqual(epubcheck["errors"][0]["id"], "OPF-001")

    def test_skipped_required_epub_validator_blocks_publish_and_writes_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_epub = make_epub(root / "source.epub")

            def skipped_validator(_path):
                return EpubValidationResult(
                    status="skipped",
                    errors=[],
                    warnings=[{"id": "JAVA_UNAVAILABLE", "message": "Java runtime not found"}],
                    checker="fake-epubcheck",
                )

            result = run_intake(
                input_path=source_epub,
                title="Book",
                author="Author",
                runs_root=root / "runs",
                config=required_epubcheck_config(),
                webdav_client=LocalWebDavClient(root / "webdav"),
                epub_validator=skipped_validator,
            )

            self.assertEqual(result.publish_report["status"], "blocked")
            self.assertIn("EPUBCheck validation status skipped", result.publish_report["reason"])
            self.assertEqual(result.manifest.update_decision, UpdateDecision.BLOCKED_RISKY)
            self.assertFalse((root / "webdav/books/Book - Author.epub").exists())
            self.assertTrue((result.reports_dir / "manifest.json").exists())
            epubcheck = json.loads((result.reports_dir / "epubcheck.json").read_text(encoding="utf-8"))
            publish_report = json.loads((result.reports_dir / "publish-report.json").read_text(encoding="utf-8"))
            self.assertEqual(epubcheck["status"], "skipped")
            self.assertEqual(publish_report["status"], "blocked")

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

    def test_unreadable_existing_remote_epub_goes_pending_without_touching_old_target(self):
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
            invalid_remote_bytes = b"not an epub"
            remote_epub.write_bytes(invalid_remote_bytes)

            result = run_intake(
                input_path=new_epub,
                title="Book",
                author="Author",
                runs_root=root / "new-runs",
                config=no_network_config(),
                webdav_client=webdav,
            )

            self.assertEqual(result.publish_report["status"], "pending")
            self.assertEqual(result.manifest.update_decision, UpdateDecision.BLOCKED_RISKY)
            self.assertEqual(remote_epub.read_bytes(), invalid_remote_bytes)
            self.assertTrue(pending_candidate_path(root / "webdav", result.publish_report).exists())
            update_diff = result.reports_dir / "update-diff.md"
            self.assertTrue(update_diff.exists())
            self.assertIn("remote EPUB unreadable", update_diff.read_text(encoding="utf-8"))

    def test_module_cli_help_exits_zero(self):
        repo_root = Path(__file__).resolve().parents[2]

        result = subprocess.run(
            [sys.executable, "-m", "scripts.hermes_books.intake", "--help"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Hermes local TXT/EPUB intake", result.stdout)


if __name__ == "__main__":
    unittest.main()
