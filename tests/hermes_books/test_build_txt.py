import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
