import tempfile
import unittest
from pathlib import Path

from scripts.hermes_books.models import BookJob
from scripts.hermes_books.sources import LocalFileSource, prepare_run_workspace


class SourceTests(unittest.TestCase):
    def test_local_file_source_copies_raw_file_and_hashes_it(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "novel.txt"
            src.write_text("第一章\n正文", encoding="utf-8")
            job = BookJob.from_input(src, "小说", "作者", root / "runs")

            snapshot = LocalFileSource(job).snapshot()

            self.assertTrue(snapshot.raw_path.exists())
            self.assertEqual(snapshot.raw_path.read_text(encoding="utf-8"), "第一章\n正文")
            self.assertEqual(snapshot.source_hash, snapshot.source_hash.lower())
            self.assertEqual(len(snapshot.source_hash), 64)

    def test_prepare_run_workspace_creates_expected_directories(self):
        with tempfile.TemporaryDirectory() as td:
            job = BookJob.from_input(Path(td) / "book.epub", "书", "作者", Path(td) / "runs")
            paths = prepare_run_workspace(job)
            self.assertTrue(paths.raw_dir.is_dir())
            self.assertTrue(paths.draft_dir.is_dir())
            self.assertTrue(paths.normalized_dir.is_dir())
            self.assertTrue(paths.reports_dir.is_dir())


if __name__ == "__main__":
    unittest.main()
