import posixpath
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from ebooklib import epub

from scripts.hermes_books.build import build_draft_from_txt
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


if __name__ == "__main__":
    unittest.main()
