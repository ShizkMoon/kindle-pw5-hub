import tempfile
import unittest
from pathlib import Path

from scripts.hermes_books.config import AssetEnrichmentConfig, HermesConfig
from scripts.hermes_books.intake import run_intake
from scripts.hermes_books.models import AssetMode
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


if __name__ == "__main__":
    unittest.main()
