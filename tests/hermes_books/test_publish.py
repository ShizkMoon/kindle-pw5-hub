import hashlib
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


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


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

    def test_new_book_with_existing_target_goes_pending_without_touching_old_book(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav = root / "webdav"
            (webdav / "books").mkdir(parents=True)
            (webdav / "books/Book - Author.epub").write_bytes(b"old")
            epub = root / "candidate.epub"
            epub.write_bytes(b"new")

            publisher = WebDavPublisher(LocalWebDavClient(webdav))
            report = publisher.publish("/books/Book - Author.epub", epub, manifest(UpdateDecision.NEW_BOOK))

            self.assertEqual((webdav / "books/Book - Author.epub").read_bytes(), b"old")
            self.assertTrue((webdav / "books/.pending/Book - Author/candidate.epub").exists())
            self.assertEqual(report["status"], "pending")

    def test_safe_append_existing_target_without_manifest_goes_pending_without_touching_old_book(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav = root / "webdav"
            (webdav / "books").mkdir(parents=True)
            remote_epub = webdav / "books/Book - Author.epub"
            old_epub_bytes = b"old"
            remote_epub.write_bytes(old_epub_bytes)
            epub = root / "candidate.epub"
            epub.write_bytes(b"new")

            publisher = WebDavPublisher(LocalWebDavClient(webdav))
            report = publisher.publish("/books/Book - Author.epub", epub, manifest(UpdateDecision.SAFE_APPEND))

            self.assertEqual(remote_epub.read_bytes(), old_epub_bytes)
            self.assertTrue((webdav / "books/.pending/Book - Author/candidate.epub").exists())
            self.assertEqual(report["status"], "pending")

    def test_safe_append_existing_target_with_unreadable_manifest_goes_pending_without_touching_old_book(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav = root / "webdav"
            (webdav / "books").mkdir(parents=True)
            remote_epub = webdav / "books/Book - Author.epub"
            old_epub_bytes = b"old"
            remote_epub.write_bytes(old_epub_bytes)
            (webdav / "books/Book - Author.hermes.json").write_bytes(b'{"old":true}')
            epub = root / "candidate.epub"
            epub.write_bytes(b"new")

            class UnreadableManifestClient(LocalWebDavClient):
                def get(self, path):
                    if path == "/books/Book - Author.hermes.json":
                        raise RuntimeError("injected manifest read failure")
                    return super().get(path)

            publisher = WebDavPublisher(UnreadableManifestClient(webdav))
            report = publisher.publish("/books/Book - Author.epub", epub, manifest(UpdateDecision.SAFE_APPEND))

            self.assertEqual(remote_epub.read_bytes(), old_epub_bytes)
            self.assertTrue((webdav / "books/.pending/Book - Author/candidate.epub").exists())
            self.assertEqual(report["status"], "pending")

    def test_safe_append_existing_target_without_expected_hashes_goes_pending_without_touching_old_book(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav = root / "webdav"
            (webdav / "books").mkdir(parents=True)
            remote_epub = webdav / "books/Book - Author.epub"
            remote_manifest = webdav / "books/Book - Author.hermes.json"
            old_epub_bytes = b"old-epub"
            old_manifest_bytes = b'{"old":true}'
            remote_epub.write_bytes(old_epub_bytes)
            remote_manifest.write_bytes(old_manifest_bytes)
            epub = root / "candidate.epub"
            epub.write_bytes(b"new-epub")

            publisher = WebDavPublisher(LocalWebDavClient(webdav))
            report = publisher.publish("/books/Book - Author.epub", epub, manifest(UpdateDecision.SAFE_APPEND))

            self.assertEqual(remote_epub.read_bytes(), old_epub_bytes)
            self.assertEqual(remote_manifest.read_bytes(), old_manifest_bytes)
            self.assertTrue((webdav / "books/.pending/Book - Author/candidate.epub").exists())
            self.assertEqual(report["status"], "pending")

    def test_safe_append_existing_target_with_expected_hash_mismatch_goes_pending_without_touching_old_book(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav = root / "webdav"
            (webdav / "books").mkdir(parents=True)
            remote_epub = webdav / "books/Book - Author.epub"
            remote_manifest = webdav / "books/Book - Author.hermes.json"
            old_epub_bytes = b"old-epub"
            old_manifest_bytes = b'{"old":true}'
            remote_epub.write_bytes(old_epub_bytes)
            remote_manifest.write_bytes(old_manifest_bytes)
            epub = root / "candidate.epub"
            epub.write_bytes(b"new-epub")

            publisher = WebDavPublisher(LocalWebDavClient(webdav))
            report = publisher.publish(
                "/books/Book - Author.epub",
                epub,
                manifest(UpdateDecision.SAFE_APPEND),
                expected_old_epub_hash=sha256_bytes(b"different-epub"),
                expected_old_manifest_hash=sha256_bytes(old_manifest_bytes),
            )

            self.assertEqual(remote_epub.read_bytes(), old_epub_bytes)
            self.assertEqual(remote_manifest.read_bytes(), old_manifest_bytes)
            self.assertTrue((webdav / "books/.pending/Book - Author/candidate.epub").exists())
            self.assertEqual(report["status"], "pending")

    def test_safe_append_existing_target_with_matching_expected_hashes_still_publishes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav = root / "webdav"
            (webdav / "books").mkdir(parents=True)
            remote_epub = webdav / "books/Book - Author.epub"
            remote_manifest = webdav / "books/Book - Author.hermes.json"
            old_epub_bytes = b"old-epub"
            old_manifest_bytes = b'{"old":true}'
            remote_epub.write_bytes(old_epub_bytes)
            remote_manifest.write_bytes(old_manifest_bytes)
            epub = root / "candidate.epub"
            epub.write_bytes(b"new-epub")

            publisher = WebDavPublisher(LocalWebDavClient(webdav))
            report = publisher.publish(
                "/books/Book - Author.epub",
                epub,
                manifest(UpdateDecision.SAFE_APPEND),
                expected_old_epub_hash=sha256_bytes(old_epub_bytes),
                expected_old_manifest_hash=sha256_bytes(old_manifest_bytes),
            )

            self.assertEqual(remote_epub.read_bytes(), b"new-epub")
            self.assertNotEqual(remote_manifest.read_bytes(), old_manifest_bytes)
            self.assertEqual(report["status"], "published")

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
            publisher.publish(
                "/books/Book - Author.epub",
                epub,
                manifest(UpdateDecision.SAFE_APPEND),
                expected_old_epub_hash=sha256_bytes(b"old-one"),
                expected_old_manifest_hash=sha256_bytes(b'{"old":1}'),
            )
            (webdav / "books/Book - Author.epub").write_bytes(b"old-two")
            (webdav / "books/Book - Author.hermes.json").write_bytes(b'{"old":2}')
            publisher.publish(
                "/books/Book - Author.epub",
                epub,
                manifest(UpdateDecision.SAFE_APPEND),
                expected_old_epub_hash=sha256_bytes(b"old-two"),
                expected_old_manifest_hash=sha256_bytes(b'{"old":2}'),
            )

            first = webdav / "books/.backups/Book - Author/20260706T010203Z"
            second = webdav / "books/.backups/Book - Author/20260706T010204Z"
            self.assertEqual((first / "old.epub").read_bytes(), b"old-one")
            self.assertEqual((first / "old.hermes.json").read_bytes(), b'{"old":1}')
            self.assertEqual((second / "old.epub").read_bytes(), b"old-two")
            self.assertEqual((second / "old.hermes.json").read_bytes(), b'{"old":2}')

    def test_safe_overwrite_restores_old_files_when_manifest_put_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav = root / "webdav"
            (webdav / "books").mkdir(parents=True)
            remote_epub = webdav / "books/Book - Author.epub"
            remote_manifest = webdav / "books/Book - Author.hermes.json"
            old_epub_bytes = b"old-epub"
            old_manifest_bytes = b'{"old":true}'
            remote_epub.write_bytes(old_epub_bytes)
            remote_manifest.write_bytes(old_manifest_bytes)
            epub = root / "candidate.epub"
            epub.write_bytes(b"new-epub")

            class FailingManifestPutClient(LocalWebDavClient):
                def __init__(self, client_root):
                    super().__init__(client_root)
                    self.epub_put_seen = False
                    self.failed_once = False

                def put(self, path, data):
                    if path == "/books/Book - Author.epub" and data == b"new-epub":
                        self.epub_put_seen = True
                    if (
                        path == "/books/Book - Author.hermes.json"
                        and self.epub_put_seen
                        and not self.failed_once
                    ):
                        self.failed_once = True
                        raise RuntimeError("injected manifest PUT failure")
                    return super().put(path, data)

            publisher = WebDavPublisher(FailingManifestPutClient(webdav))

            with self.assertRaisesRegex(RuntimeError, "injected manifest PUT failure"):
                publisher.publish(
                    "/books/Book - Author.epub",
                    epub,
                    manifest(UpdateDecision.SAFE_APPEND),
                    expected_old_epub_hash=sha256_bytes(old_epub_bytes),
                    expected_old_manifest_hash=sha256_bytes(old_manifest_bytes),
                )

            self.assertEqual(remote_epub.read_bytes(), old_epub_bytes)
            self.assertEqual(remote_manifest.read_bytes(), old_manifest_bytes)

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
