import tempfile
import unittest
from pathlib import Path

from scripts.hermes_books.inspect import inspect_epub, write_quality_report
from tests.hermes_books.helpers import make_epub


class InspectTests(unittest.TestCase):
    def test_inspect_extracts_chapters_identifier_css_issues_and_cover_status(self):
        with tempfile.TemporaryDirectory() as td:
            epub_path = make_epub(Path(td) / "book.epub", css="p { font-size: 16px; }")
            report = inspect_epub(epub_path)

            self.assertEqual(report.title, "Book")
            self.assertEqual(report.author, "Author")
            self.assertEqual(report.opf_identifier, "urn:test:book-author")
            self.assertEqual(len(report.chapters), 2)
            self.assertTrue(report.missing_cover)
            self.assertTrue(any(issue.code == "CSS_ABSOLUTE_FONT_SIZE" for issue in report.issues))

    def test_write_quality_report_contains_human_summary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            epub_path = make_epub(root / "book.epub")
            report = inspect_epub(epub_path)
            out = write_quality_report(report, root / "quality-report.md")
            text = out.read_text(encoding="utf-8")
            self.assertIn("EPUB quality report", text)
            self.assertIn("Chapters: 2", text)


if __name__ == "__main__":
    unittest.main()
