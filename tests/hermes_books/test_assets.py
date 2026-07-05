import tempfile
import unittest
from pathlib import Path

from scripts.hermes_books.assets import AssetCandidate, AssetEnricher
from scripts.hermes_books.config import AssetEnrichmentConfig
from scripts.hermes_books.inspect import inspect_epub
from scripts.hermes_books.models import AssetMode
from tests.hermes_books.helpers import make_epub


class FakeProvider:
    def candidates(self, title: str, author: str, role: str):
        source_url = f"https://assets.example/{role}.jpg"
        return [
            AssetCandidate(
                role=role,
                source_url=source_url,
                local_path=Path(f"{role}.jpg"),
                width=1600,
                height=2400,
                confidence=0.93,
                reason=f"fake high confidence {role}",
            )
        ]


class AssetTests(unittest.TestCase):
    def test_cover_is_auto_selected_when_missing_and_confident(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            epub_path = make_epub(root / "book.epub")
            report = inspect_epub(epub_path)
            enricher = AssetEnricher(AssetEnrichmentConfig(mode=AssetMode.BALANCED), FakeProvider())

            asset_report = enricher.plan("Book", "Author", report, root)

            self.assertEqual(asset_report.auto_adopted[0].role, "cover")
            self.assertEqual(asset_report.auto_adopted[0].confidence, 0.93)

    def test_low_confidence_candidate_goes_to_pending(self):
        class LowProvider:
            def candidates(self, title: str, author: str, role: str):
                return [
                    AssetCandidate(
                        role,
                        "https://assets.example/x.jpg",
                        Path("x.jpg"),
                        500,
                        700,
                        0.5,
                        "weak",
                    )
                ]

        with tempfile.TemporaryDirectory() as td:
            report = inspect_epub(make_epub(Path(td) / "book.epub"))
            enricher = AssetEnricher(AssetEnrichmentConfig(mode=AssetMode.BALANCED), LowProvider())
            asset_report = enricher.plan("Book", "Author", report, Path(td))
            self.assertEqual(asset_report.auto_adopted, [])
            self.assertEqual(asset_report.pending[0].confidence, 0.5)

    def test_only_top_cover_candidate_is_auto_adopted(self):
        class MultiCoverProvider:
            def candidates(self, title: str, author: str, role: str):
                return [
                    AssetCandidate(role, f"https://assets.example/{idx}.jpg", Path(f"{idx}.jpg"), 1000, 1500, 0.95, str(idx))
                    for idx in range(3)
                ]

        with tempfile.TemporaryDirectory() as td:
            report = inspect_epub(make_epub(Path(td) / "book.epub"))
            enricher = AssetEnricher(AssetEnrichmentConfig(mode=AssetMode.BALANCED), MultiCoverProvider())

            asset_report = enricher.plan("Book", "Author", report, Path(td))

            self.assertEqual(len(asset_report.auto_adopted), 1)
            self.assertEqual(asset_report.auto_adopted[0].source_url, "https://assets.example/0.jpg")
            self.assertEqual([candidate.source_url for candidate in asset_report.pending], [
                "https://assets.example/1.jpg",
                "https://assets.example/2.jpg",
            ])

    def test_aggressive_illustrations_stay_pending_until_insertion_is_supported(self):
        with tempfile.TemporaryDirectory() as td:
            report = inspect_epub(make_epub(Path(td) / "book.epub"))
            enricher = AssetEnricher(AssetEnrichmentConfig(mode=AssetMode.AGGRESSIVE), FakeProvider())

            asset_report = enricher.plan("Book", "Author", report, Path(td))

            self.assertEqual([candidate.role for candidate in asset_report.auto_adopted], ["cover"])
            self.assertIn("illustration", [candidate.role for candidate in asset_report.pending])


if __name__ == "__main__":
    unittest.main()
