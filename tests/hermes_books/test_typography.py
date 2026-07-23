import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.hermes_books.build import normalize_existing_epub
from scripts.hermes_books.config import TypographyConfig, TypographyMode
from scripts.hermes_books.models import BookJob
from scripts.hermes_books.typography import (
    TypographyMutationStats,
    audit_epub_typography,
    write_typography_reports,
)
from tests.hermes_books.helpers import make_epub


def replace_entry(path: Path, name: str, content: bytes) -> None:
    with zipfile.ZipFile(path, "r") as source:
        infos = source.infolist()
        entries = {info.filename: source.read(info.filename) for info in infos}
    entries[name] = content
    with zipfile.ZipFile(path, "w") as target:
        for info in infos:
            target.writestr(info, entries[info.filename])


class TypographyTests(unittest.TestCase):
    def test_normalization_converts_fixed_typography_and_adds_polished_profile(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_epub(
                root / "source.epub",
                css=(
                    "@font-face { font-family: Locked; src: url(font.otf); }\n"
                    "body { font-size: 16px; line-height: 24px; }"
                ),
            )
            with zipfile.ZipFile(source) as archive:
                chapter = archive.read("EPUB/chapters/ch0001.xhtml").decode("utf-8")
            chapter = chapter.replace(
                "<p>", '<p style="font-size: 12pt; line-height: 20px">', 1
            )
            replace_entry(source, "EPUB/chapters/ch0001.xhtml", chapter.encode("utf-8"))

            job = BookJob.from_input(source, "Book", "Author", root / "runs")
            stats = TypographyMutationStats()
            normalized = normalize_existing_epub(
                job,
                source,
                root / "normalized",
                TypographyConfig(),
                stats,
            )

            with zipfile.ZipFile(normalized) as archive:
                css = archive.read("EPUB/styles/style.css").decode("utf-8")
                profile = archive.read("EPUB/styles/hermes-normalized.css").decode("utf-8")
                chapter = archive.read("EPUB/chapters/ch0001.xhtml").decode("utf-8")
            self.assertIn("font-size: 1em", css)
            self.assertIn("line-height: 1.5em", css)
            self.assertIn("font-size: 1em", chapter)
            self.assertIn("line-height: 1.25em", chapter)
            self.assertIn("text-justify: inter-ideograph", profile)
            self.assertIn("img, svg", profile)
            self.assertGreaterEqual(stats.stylesheet_links_added, 2)
            self.assertEqual(stats.css_font_sizes_normalized, 2)
            self.assertEqual(stats.css_line_heights_normalized, 2)

            report = audit_epub_typography(normalized, TypographyConfig(), stats)
            self.assertEqual(report.status, "warnings")
            self.assertEqual(report.documents_checked, report.documents_with_profile)
            self.assertNotIn("HIGH", {issue.severity for issue in report.issues})
            self.assertIn("EMBEDDED_FONT_FACE", {issue.code for issue in report.issues})

    def test_audit_only_reports_missing_profile_without_mutating_source_styles(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_epub(root / "source.epub", css="body { font-size: 16px; }")
            job = BookJob.from_input(source, "Book", "Author", root / "runs")
            config = TypographyConfig(mode=TypographyMode.AUDIT_ONLY)

            normalized = normalize_existing_epub(job, source, root / "normalized", config)
            report = audit_epub_typography(normalized, config)

            self.assertEqual(report.status, "failed")
            codes = {issue.code for issue in report.issues}
            self.assertIn("PROFILE_STYLESHEET_MISSING", codes)
            self.assertIn("CSS_ABSOLUTE_TYPOGRAPHY", codes)

    def test_writes_machine_and_human_typography_reports(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_epub(root / "source.epub")
            job = BookJob.from_input(source, "Book", "Author", root / "runs")
            normalized = normalize_existing_epub(job, source, root / "normalized")
            report = audit_epub_typography(normalized, TypographyConfig())

            write_typography_reports(report, root / "reports")

            payload = json.loads((root / "reports/typography-report.json").read_text(encoding="utf-8"))
            markdown = (root / "reports/typography-report.md").read_text(encoding="utf-8")
            self.assertEqual(payload["profile"], "koreader-literary")
            self.assertIn("Deterministic changes", markdown)

    def test_typography_literals_in_comments_or_visible_text_are_not_rewritten_or_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_epub(
                root / "source.epub",
                chapters=[("第一章", "示例代码 font-size: 12px 不应被改写")],
                css="/* example: font-size: 12px */ p { text-indent: 2em; }",
            )
            job = BookJob.from_input(source, "Book", "Author", root / "runs")

            normalized = normalize_existing_epub(job, source, root / "normalized")
            report = audit_epub_typography(normalized, TypographyConfig())

            with zipfile.ZipFile(normalized) as archive:
                css = archive.read("EPUB/styles/style.css").decode("utf-8")
                chapter = archive.read("EPUB/chapters/ch0001.xhtml").decode("utf-8")
            self.assertIn("font-size: 12px", css)
            self.assertIn("font-size: 12px", chapter)
            self.assertNotIn(
                "CSS_ABSOLUTE_TYPOGRAPHY",
                {issue.code for issue in report.issues},
            )
            self.assertNotIn(
                "INLINE_ABSOLUTE_TYPOGRAPHY",
                {issue.code for issue in report.issues},
            )


if __name__ == "__main__":
    unittest.main()
