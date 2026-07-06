import posixpath
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from ebooklib import epub

from scripts.hermes_books.build import build_draft_from_txt, normalize_existing_epub
from scripts.hermes_books.models import BookJob
from scripts.hermes_books.sources import LocalFileSource, prepare_run_workspace


class TxtBuildTests(unittest.TestCase):
    def test_txt_builds_draft_epub_then_can_be_read_by_ebooklib(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            txt = root / "novel.txt"
            txt.write_text(
                "第一章 开始\n"
                "这是第一段。\n\n"
                "第二章 继续\n"
                "这是第二段。\n",
                encoding="utf-8",
            )
            job = BookJob.from_input(txt, "测试小说", "作者", root / "runs")
            snapshot = LocalFileSource(job).snapshot()
            paths = prepare_run_workspace(job)

            draft = build_draft_from_txt(job, snapshot.raw_path, paths.draft_dir)

            self.assertTrue(draft.exists())
            book = epub.read_epub(str(draft))
            self.assertEqual(book.get_metadata("DC", "title")[0][0], "测试小说")
            html_names = sorted(item.file_name for item in book.get_items() if item.file_name.endswith(".xhtml"))
            self.assertIn("chapters/ch0001.xhtml", html_names)
            self.assertIn("chapters/ch0002.xhtml", html_names)
            with zipfile.ZipFile(draft) as archive:
                archive_names = set(archive.namelist())
                chapter_names = sorted(
                    name for name in archive_names if name.startswith("EPUB/chapters/") and name.endswith(".xhtml")
                )
                self.assertTrue(chapter_names)
                for chapter_name in chapter_names:
                    root_element = ElementTree.fromstring(archive.read(chapter_name))
                    stylesheet_hrefs = [
                        element.attrib["href"]
                        for element in root_element.findall(".//{http://www.w3.org/1999/xhtml}link")
                        if element.attrib.get("rel") == "stylesheet" and element.attrib.get("href")
                    ]
                    self.assertTrue(stylesheet_hrefs, chapter_name)
                    for href in stylesheet_hrefs:
                        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(chapter_name), href))
                        self.assertIn(resolved, archive_names)

    def test_epub_input_normalization_injects_hermes_stylesheet(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.epub"
            book = epub.EpubBook()
            book.set_identifier("urn:test:source")
            book.set_title("Book")
            book.set_language("zh")
            book.add_author("Author")
            chapter = epub.EpubHtml(title="第一章", file_name="chapters/ch0001.xhtml", lang="zh")
            chapter.content = (
                "<?xml version='1.0' encoding='utf-8'?>"
                "<html xmlns='http://www.w3.org/1999/xhtml'><head><title>第一章</title></head>"
                "<body><h2>第一章</h2><p>正文</p></body></html>"
            ).encode("utf-8")
            book.add_item(chapter)
            book.toc = [epub.Link(chapter.file_name, "第一章", "ch0001")]
            book.spine = ["nav", chapter]
            book.add_item(epub.EpubNcx())
            book.add_item(epub.EpubNav())
            epub.write_epub(str(source), book)

            job = BookJob.from_input(source, "Book", "Author", root / "runs")
            normalized = normalize_existing_epub(job, source, root / "normalized")

            self.assertNotEqual(normalized.read_bytes(), source.read_bytes())
            with zipfile.ZipFile(normalized) as archive:
                archive_names = set(archive.namelist())
                self.assertIn("EPUB/styles/hermes-normalized.css", archive_names)
                root_element = ElementTree.fromstring(archive.read("EPUB/chapters/ch0001.xhtml"))
                stylesheet_hrefs = [
                    element.attrib["href"]
                    for element in root_element.findall(".//{http://www.w3.org/1999/xhtml}link")
                    if element.attrib.get("rel") == "stylesheet"
                ]
                self.assertIn("../styles/hermes-normalized.css", stylesheet_hrefs)

            normalized_again = normalize_existing_epub(job, normalized, root / "normalized-again")
            with zipfile.ZipFile(normalized_again) as archive:
                names = [name for name in archive.namelist() if "hermes-normalized" in name]
                self.assertEqual(names.count("EPUB/styles/hermes-normalized.css"), 1)
                self.assertNotIn("EPUB/styles/hermes-normalized-2.css", names)


if __name__ == "__main__":
    unittest.main()
