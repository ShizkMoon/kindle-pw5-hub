import json
import tempfile
import unittest
from pathlib import Path

from scripts.hermes_books.config import MetadataEnrichmentConfig, MetadataEnrichmentMode
from scripts.hermes_books.metadata import (
    MetadataDecision,
    MetadataEnricher,
    MetadataEvidence,
    MetadataResolution,
    write_metadata_reports,
)


class MetadataTests(unittest.TestCase):
    def test_enricher_applies_only_confident_evidence_backed_decisions(self):
        config = MetadataEnrichmentConfig(auto_apply_min_confidence=0.86, require_evidence_url=True)
        evidence = [
            MetadataEvidence("store-1", "store", "https://example.test/books/1", {"title": "标准书名"}),
            MetadataEvidence("guess-1", "llm", "", {"publisher": "未知出版社"}),
        ]
        resolution = MetadataResolution(
            decisions=[
                MetadataDecision("title", "旧书名", "标准书名", "apply", 0.93, ["store-1"], "store match"),
                MetadataDecision("publisher", "", "未知出版社", "apply", 0.95, ["guess-1"], "no url"),
                MetadataDecision("isbn", "", "9780000000000", "apply", 0.40, ["store-1"], "low confidence"),
            ]
        )

        report = MetadataEnricher(config).decide(evidence, resolution)

        self.assertEqual([decision.field for decision in report.applied_decisions], ["title"])
        self.assertEqual({decision.field for decision in report.reported_decisions}, {"publisher", "isbn"})

    def test_report_only_mode_never_applies_decisions(self):
        config = MetadataEnrichmentConfig(mode=MetadataEnrichmentMode.REPORT_ONLY)
        evidence = [
            MetadataEvidence("store-1", "store", "https://example.test/books/1", {"title": "标准书名"}),
        ]
        resolution = MetadataResolution(
            decisions=[
                MetadataDecision("title", "旧书名", "标准书名", "apply", 0.99, ["store-1"], "store match"),
            ]
        )

        report = MetadataEnricher(config).decide(evidence, resolution)

        self.assertEqual(report.status, "reported")
        self.assertEqual(report.applied_decisions, [])
        self.assertEqual([decision.field for decision in report.reported_decisions], ["title"])

    def test_block_decision_becomes_conflict(self):
        config = MetadataEnrichmentConfig()
        resolution = MetadataResolution(
            decisions=[
                MetadataDecision(
                    "identity",
                    "Book 1",
                    "Book 2",
                    "block",
                    0.98,
                    ["store-1"],
                    "evidence points to another volume",
                ),
            ]
        )

        report = MetadataEnricher(config).decide([], resolution)

        self.assertEqual(report.status, "blocked")
        self.assertEqual(report.conflicts[0].field, "identity")

    def test_single_source_fields_are_reported_when_disabled(self):
        config = MetadataEnrichmentConfig(allow_single_source_fields=False)
        evidence = [
            MetadataEvidence("store-1", "store", "https://example.test/books/1", {"title": "标准书名"}),
        ]
        resolution = MetadataResolution(
            decisions=[
                MetadataDecision("title", "旧书名", "标准书名", "apply", 0.99, ["store-1"], "one source only"),
            ]
        )

        report = MetadataEnricher(config).decide(evidence, resolution)

        self.assertEqual(report.status, "reported")
        self.assertEqual(report.applied_decisions, [])
        self.assertEqual(report.reported_decisions[0].field, "title")

    def test_identity_conflict_can_be_reported_instead_of_blocking(self):
        config = MetadataEnrichmentConfig(block_on_conflicting_identity=False)
        resolution = MetadataResolution(
            decisions=[
                MetadataDecision(
                    "identity",
                    "Book 1",
                    "Book 2",
                    "block",
                    0.98,
                    ["store-1"],
                    "evidence points to another volume",
                ),
            ]
        )

        report = MetadataEnricher(config).decide([], resolution)

        self.assertEqual(report.status, "reported")
        self.assertEqual(report.conflicts, [])
        self.assertEqual(report.reported_decisions[0].field, "identity")

    def test_write_metadata_reports(self):
        report = MetadataEnricher(MetadataEnrichmentConfig()).decide(
            [MetadataEvidence("store-1", "store", "https://example.test/books/1", {"title": "标准书名"})],
            MetadataResolution(
                decisions=[
                    MetadataDecision("title", "旧书名", "标准书名", "apply", 0.93, ["store-1"], "store match"),
                ]
            ),
        )
        with tempfile.TemporaryDirectory() as td:
            reports_dir = Path(td)

            write_metadata_reports(report, reports_dir)

            raw = json.loads((reports_dir / "metadata-report.json").read_text(encoding="utf-8"))
            self.assertEqual(raw["status"], "applied")
            self.assertIn("已自动补全", (reports_dir / "metadata-report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
