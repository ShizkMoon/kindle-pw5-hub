import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.hermes_books.config import (
    AssetEnrichmentConfig,
    HermesConfig,
    OnlineEnrichmentConfig,
    PipelineConfig,
)
from scripts.hermes_books.intake import run_intake
from scripts.hermes_books.models import AssetMode
from scripts.hermes_books.publish import LocalWebDavClient
from tests.hermes_books.helpers import make_epub
from tests.hermes_books.test_online_metadata import GOOGLE_PAYLOAD, OPEN_LIBRARY_PAYLOAD


class OnlineIntakeTests(unittest.TestCase):
    def test_configured_online_enrichment_is_wired_into_intake(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_epub(
                root / "source.epub",
                title="测试小说",
                author="测试作者",
            )
            config = HermesConfig(
                pipeline=PipelineConfig(require_epubcheck=False),
                asset_enrichment=AssetEnrichmentConfig(mode=AssetMode.OFF),
                online_enrichment=OnlineEnrichmentConfig(enabled=True),
            )

            def fetch(_fetcher, url: str):
                if "googleapis.com" in url:
                    return GOOGLE_PAYLOAD
                if "openlibrary.org" in url:
                    return OPEN_LIBRARY_PAYLOAD
                raise AssertionError(url)

            with (
                patch(
                    "scripts.hermes_books.online_metadata.CachedJsonFetcher.__call__",
                    autospec=True,
                    side_effect=fetch,
                ),
                patch(
                    "scripts.hermes_books.intake.OnlineCoverFetcher",
                    return_value=lambda _report: b"\xff\xd8\xffcover",
                ),
            ):
                result = run_intake(
                    source,
                    "测试小说",
                    "测试作者",
                    root / "runs",
                    config,
                    webdav_client=LocalWebDavClient(root / "webdav"),
                )

            metadata = json.loads(
                (result.reports_dir / "metadata-report.json").read_text(encoding="utf-8")
            )
            typography = json.loads(
                (result.reports_dir / "typography-report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(result.publish_report["status"], "published")
            self.assertEqual(metadata["resolver"], "deterministic-consensus-v1")
            self.assertEqual({item["source"] for item in metadata["evidence"]}, {
                "google-books",
                "open-library",
            })
            self.assertIn("cover", {item["field"] for item in metadata["applied_decisions"]})
            self.assertNotEqual(typography["status"], "failed")
            self.assertEqual(result.manifest.typography_report["profile"], "koreader-literary")


if __name__ == "__main__":
    unittest.main()
