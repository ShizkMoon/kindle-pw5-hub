import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.hermes_books.inspect import inspect_epub, write_quality_report
from tests.hermes_books.helpers import make_epub, reverse_spine_chapters


def _add_epub3_cover_image_property(epub_path: Path) -> None:
    with zipfile.ZipFile(epub_path, "r") as source:
        entries = {name: source.read(name) for name in source.namelist()}

    opf_path = "EPUB/content.opf"
    opf = entries[opf_path].decode("utf-8")
    opf = opf.replace(
        "</manifest>",
        '    <item href="images/front.jpg" id="img1" media-type="image/jpeg" properties="cover-image"/>\n'
        "  </manifest>",
    )
    entries[opf_path] = opf.encode("utf-8")
    entries["EPUB/images/front.jpg"] = b"fake image bytes"

    with zipfile.ZipFile(epub_path, "w") as target:
        for name, content in entries.items():
            target.writestr(name, content)


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

    def test_chapter_fingerprint_ignores_head_title_and_heading_text(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first_path = make_epub(root / "first.epub", chapters=[("Original Heading", "Same body")])
            second_path = make_epub(root / "second.epub", chapters=[("Corrected Heading", "Same body")])

            first = inspect_epub(first_path)
            second = inspect_epub(second_path)

            self.assertEqual(first.chapters[0].fingerprint, second.chapters[0].fingerprint)
            self.assertEqual(
                first.chapters[0].structure_fingerprint,
                second.chapters[0].structure_fingerprint,
            )
            self.assertEqual(first.chapters[0].text_chars, second.chapters[0].text_chars)

    def test_chapter_named_chapter_nav_is_not_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            epub_path = make_epub(
                Path(td) / "book.epub",
                chapters=[("Chapter Nav", "Real chapter body")],
                chapter_file_names=["chapters/chapter-nav.xhtml"],
            )

            report = inspect_epub(epub_path)

            self.assertEqual(len(report.chapters), 1)
            self.assertEqual(report.chapters[0].href, "chapters/chapter-nav.xhtml")

    def test_chapters_follow_spine_order_not_manifest_order(self):
        with tempfile.TemporaryDirectory() as td:
            epub_path = make_epub(
                Path(td) / "book.epub",
                chapters=[("First", "First body"), ("Second", "Second body")],
            )
            reverse_spine_chapters(epub_path)

            report = inspect_epub(epub_path)

            self.assertEqual(
                [chapter.href for chapter in report.chapters],
                ["chapters/ch0002.xhtml", "chapters/ch0001.xhtml"],
            )
            self.assertEqual([chapter.item_id for chapter in report.chapters], ["chapter_1", "chapter_0"])

    def test_cover_metadata_detects_cover_with_non_cover_filename(self):
        with tempfile.TemporaryDirectory() as td:
            epub_path = make_epub(Path(td) / "book.epub", cover_file_name="images/frontispiece.jpg")

            report = inspect_epub(epub_path)

            self.assertFalse(report.missing_cover)
            self.assertTrue(
                any(image.href == "images/frontispiece.jpg" and image.role == "cover" for image in report.images)
            )

    def test_epub3_cover_image_manifest_property_detects_non_cover_filename(self):
        with tempfile.TemporaryDirectory() as td:
            epub_path = make_epub(Path(td) / "book.epub")
            _add_epub3_cover_image_property(epub_path)

            report = inspect_epub(epub_path)

            self.assertFalse(report.missing_cover)
            self.assertTrue(
                any(image.href == "images/front.jpg" and image.role == "cover" for image in report.images)
            )


if __name__ == "__main__":
    unittest.main()
