import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from scripts.hermes_books.models import BookManifest, UpdateDecision
from scripts.hermes_books.publish import HttpWebDavClient, LocalWebDavClient, WebDavPublisher


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
    def test_local_webdav_client_rejects_escape_paths(self):
        with tempfile.TemporaryDirectory() as td:
            client = LocalWebDavClient(Path(td) / "webdav")

            for bad_path in ["/books/../../outside.epub", r"..\outside.epub", r"C:\tmp\x.epub"]:
                with self.subTest(path=bad_path):
                    with self.assertRaises(ValueError):
                        client.put(bad_path, b"data")

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

    def test_repeated_safe_publish_uses_timestamped_backup_directories(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav = root / "webdav"
            (webdav / "books").mkdir(parents=True)
            (webdav / "books/Book - Author.epub").write_bytes(b"old-one")
            (webdav / "books/Book - Author.hermes.json").write_bytes(b'{"old":1}')
            epub = root / "candidate.epub"
            epub.write_bytes(b"new")
            timestamps = iter(["20260706T010203Z", "20260706T010204Z"])

            publisher = WebDavPublisher(LocalWebDavClient(webdav), timestamp=lambda: next(timestamps))
            publisher.publish("/books/Book - Author.epub", epub, manifest(UpdateDecision.SAFE_APPEND))
            (webdav / "books/Book - Author.epub").write_bytes(b"old-two")
            (webdav / "books/Book - Author.hermes.json").write_bytes(b'{"old":2}')
            publisher.publish("/books/Book - Author.epub", epub, manifest(UpdateDecision.SAFE_APPEND))

            first = webdav / "books/.backups/Book - Author/20260706T010203Z"
            second = webdav / "books/.backups/Book - Author/20260706T010204Z"
            self.assertEqual((first / "old.epub").read_bytes(), b"old-one")
            self.assertEqual((first / "old.hermes.json").read_bytes(), b'{"old":1}')
            self.assertEqual((second / "old.epub").read_bytes(), b"old-two")
            self.assertEqual((second / "old.hermes.json").read_bytes(), b'{"old":2}')

    def test_http_webdav_client_quotes_path_segments(self):
        captured = []
        original_urlopen = urllib.request.urlopen

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b""

        def fake_urlopen(req, timeout):
            captured.append(req.full_url)
            return FakeResponse()

        try:
            urllib.request.urlopen = fake_urlopen
            HttpWebDavClient("https://dav.example/root").get("/books/书 名 #1.epub")
        finally:
            urllib.request.urlopen = original_urlopen

        self.assertEqual(captured, ["https://dav.example/root/books/%E4%B9%A6%20%E5%90%8D%20%231.epub"])

    def test_http_webdav_client_mkdir_creates_nested_collections(self):
        calls = []

        class CapturingClient(HttpWebDavClient):
            def _request(self, path, method, data=None):
                calls.append((method, path))
                if path == "/books":
                    raise urllib.error.HTTPError(path, 405, "exists", {}, None)
                return b""

        CapturingClient("https://dav.example/root").mkdir("/books/.pending/Slug")

        self.assertEqual(
            calls,
            [
                ("MKCOL", "/books"),
                ("MKCOL", "/books/.pending"),
                ("MKCOL", "/books/.pending/Slug"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
