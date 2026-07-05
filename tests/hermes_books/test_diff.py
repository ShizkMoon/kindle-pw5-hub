import tempfile
import unittest
from pathlib import Path

from scripts.hermes_books.diff import compare_for_update
from scripts.hermes_books.inspect import inspect_epub
from scripts.hermes_books.models import BookManifest, UpdateDecision
from tests.hermes_books.helpers import make_epub


def manifest(title="Book", author="Author"):
    return BookManifest(
        canonical_id="book::author",
        title=title,
        author=author,
        opf_identifier="urn:test:book-author",
        source_hash="s",
        output_hash="o",
    )


class DiffTests(unittest.TestCase):
    def test_append_new_chapter_is_safe_append(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = inspect_epub(
                make_epub(root / "old.epub", chapters=[("第一章", "A"), ("第二章", "B")])
            )
            new = inspect_epub(
                make_epub(
                    root / "new.epub",
                    chapters=[("第一章", "A"), ("第二章", "B"), ("第三章", "C")],
                )
            )

            result = compare_for_update(manifest(), manifest(), old, new)

            self.assertEqual(result.decision, UpdateDecision.SAFE_APPEND)

    def test_removed_chapter_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = inspect_epub(
                make_epub(root / "old.epub", chapters=[("第一章", "A"), ("第二章", "B")])
            )
            new = inspect_epub(make_epub(root / "new.epub", chapters=[("第一章", "A")]))

            result = compare_for_update(manifest(), manifest(), old, new)

            self.assertEqual(result.decision, UpdateDecision.BLOCKED_RISKY)
            self.assertIn("chapter count decreased", result.reasons[0])

    def test_metadata_only_change_is_safe_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = inspect_epub(make_epub(root / "old.epub", chapters=[("第一章", "A")]))
            new = inspect_epub(
                make_epub(root / "new.epub", title="Book Revised", chapters=[("第一章", "A")])
            )

            result = compare_for_update(manifest(), manifest(), old, new)

            self.assertEqual(result.decision, UpdateDecision.SAFE_METADATA)


if __name__ == "__main__":
    unittest.main()
