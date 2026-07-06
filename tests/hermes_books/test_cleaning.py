import tempfile
import unittest
from pathlib import Path

from scripts.hermes_books.cleaning import (
    CleaningFinding,
    CleaningPlanner,
    TextCleaningConfig,
    write_cleaning_reports,
)
from scripts.hermes_books.inspect import inspect_epub
from tests.hermes_books.helpers import make_epub


class StaticCleaningAnalyzer:
    def analyze(self, inspection, budget):
        return [
            CleaningFinding(
                category="advertisement",
                severity="medium",
                location="chapters/ch0001.xhtml",
                message="疑似站点广告",
                confidence=0.91,
                recommendation="report-only",
            )
        ]


class CleaningTests(unittest.TestCase):
    def test_planner_without_analyzer_writes_report_only_cost_plan(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            epub_path = make_epub(root / "source.epub")
            inspection = inspect_epub(epub_path)

            report = CleaningPlanner(TextCleaningConfig()).plan(inspection)

            self.assertEqual(report.status, "planned")
            self.assertEqual(report.cost_plan["selected_route"], "rules-first-report-only")
            self.assertGreater(report.cost_plan["estimated_input_tokens"], 0)
            self.assertEqual(report.findings, [])
            self.assertIn("not configured", report.errors[0])

    def test_injected_analyzer_can_report_findings_without_body_rewrite(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            epub_path = make_epub(root / "source.epub")
            before = epub_path.read_bytes()
            inspection = inspect_epub(epub_path)

            report = CleaningPlanner(TextCleaningConfig()).plan(inspection, analyzer=StaticCleaningAnalyzer())

            self.assertEqual(report.status, "reported")
            self.assertEqual(report.findings[0].category, "advertisement")
            self.assertEqual(epub_path.read_bytes(), before)

    def test_write_cleaning_reports_outputs_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            epub_path = make_epub(root / "source.epub")
            report = CleaningPlanner(TextCleaningConfig()).plan(inspect_epub(epub_path))

            write_cleaning_reports(report, root / "reports")

            self.assertTrue((root / "reports/cleaning-report.json").exists())
            self.assertIn("Text cleaning report", (root / "reports/cleaning-report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
