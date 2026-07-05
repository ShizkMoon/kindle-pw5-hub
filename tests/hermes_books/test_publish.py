import tempfile
import unittest
from pathlib import Path

from scripts.hermes_books.models import BookManifest, UpdateDecision
from scripts.hermes_books.publish import LocalWebDavClient, WebDavPublisher


def manifest(decision):
    return BookManifest(
        canonical_id="book::author",
        title="Book",
        author="Author",
        opf_identifier="urn:test",
        source_hash="s",
        output_hash="o",
        update_decision=decision,
    )


class PublishTests(unittest.TestCase):
    def test_new_book_uploads_epub_and_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            epub = root / "book.epub"
            epub.write_bytes(b"epub")
            client = LocalWebDavClient(root / "webdav")
            publisher = WebDavPublisher(client)

            report = publisher.publish("/books/Book - Author.epub", epub, manifest(UpdateDecision.NEW_BOOK))

            self.assertTrue((root / "webdav/books/Book - Author.epub").exists())
            self.assertTrue((root / "webdav/books/Book - Author.hermes.json").exists())
            self.assertEqual(report["status"], "published")

    def test_risky_update_goes_to_pending_without_touching_old_book(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav = root / "webdav"
            (webdav / "books").mkdir(parents=True)
            (webdav / "books/Book - Author.epub").write_bytes(b"old")
            epub = root / "candidate.epub"
            epub.write_bytes(b"new")

            publisher = WebDavPublisher(LocalWebDavClient(webdav))
            report = publisher.publish("/books/Book - Author.epub", epub, manifest(UpdateDecision.BLOCKED_RISKY))

            self.assertEqual((webdav / "books/Book - Author.epub").read_bytes(), b"old")
            self.assertTrue((webdav / "books/.pending/Book - Author/candidate.epub").exists())
            self.assertEqual(report["status"], "pending")


if __name__ == "__main__":
    unittest.main()
