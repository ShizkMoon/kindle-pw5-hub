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

    def test_new_book_manifest_write_failure_removes_live_epub_and_goes_pending(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav = root / "webdav"
            epub = root / "candidate.epub"
            epub.write_bytes(b"new-epub")

            class FailingManifestCreateClient(LocalWebDavClient):
                def put_if_absent(self, path, data):
                    if path == "/books/Book - Author.hermes.json":
                        raise RuntimeError("manifest create failed")
                    return super().put_if_absent(path, data)

            publisher = WebDavPublisher(FailingManifestCreateClient(webdav))
            report = publisher.publish("/books/Book - Author.epub", epub, manifest(UpdateDecision.NEW_BOOK))

            self.assertEqual(report["status"], "pending")
            self.assertIn("new manifest write failed", report["reason"])
            self.assertFalse((webdav / "books/Book - Author.epub").exists())
            self.assertTrue((webdav / "books/.pending/Book - Author/candidate.epub").exists())

    def test_new_book_without_verified_publish_support_goes_pending_without_creating_live_epub(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav = root / "webdav"
            epub = root / "candidate.epub"
            epub.write_bytes(b"new-epub")

            class UnsupportedNewPublishClient(LocalWebDavClient):
                supports_new_publish = False

                def put_if_absent(self, path, data):
                    if path == "/books/Book - Author.epub":
                        raise AssertionError("live EPUB must not be created")
                    return super().put_if_absent(path, data)

            publisher = WebDavPublisher(UnsupportedNewPublishClient(webdav))
            report = publisher.publish("/books/Book - Author.epub", epub, manifest(UpdateDecision.NEW_BOOK))

            self.assertEqual(report["status"], "pending")
            self.assertIn("verified conditional WebDAV support", report["reason"])
            self.assertFalse((webdav / "books/Book - Author.epub").exists())
            self.assertTrue((webdav / "books/.pending/Book - Author/candidate.epub").exists())

    def test_new_book_supported_non_local_client_publishes_manifest_before_epub(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav = root / "webdav"
            epub = root / "candidate.epub"
            epub.write_bytes(b"new-epub")
            writes = []

            class SupportedHttpLikeClient:
                supports_new_publish = True
                supports_existing_overwrite = True

                def __init__(self, client_root):
                    self.inner = LocalWebDavClient(client_root)

                def stat(self, path):
                    return self.inner.stat(path)

                def exists(self, path):
                    return self.inner.exists(path)

                def get(self, path):
                    return self.inner.get(path)

                def put(self, path, data):
                    return self.inner.put(path, data)

                def put_if_absent(self, path, data):
                    writes.append(path)
                    return self.inner.put_if_absent(path, data)

                def put_if_match(self, path, data, etag):
                    return self.inner.put_if_match(path, data, etag)

                def delete_if_match(self, path, etag):
                    return self.inner.delete_if_match(path, etag)

                def mkdir(self, path):
                    return self.inner.mkdir(path)

            publisher = WebDavPublisher(SupportedHttpLikeClient(webdav))
            report = publisher.publish("/books/Book - Author.epub", epub, manifest(UpdateDecision.NEW_BOOK))

            self.assertEqual(report["status"], "published")
            self.assertEqual(writes, ["/books/Book - Author.hermes.json", "/books/Book - Author.epub"])
            self.assertTrue((webdav / "books/Book - Author.epub").exists())
            self.assertTrue((webdav / "books/Book - Author.hermes.json").exists())

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

    def test_safe_append_without_transactional_overwrite_support_goes_pending_without_touching_old_book(self):
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

            class NonTransactionalClient(LocalWebDavClient):
                supports_existing_overwrite = False

                def put_if_match(self, path, data, etag):
                    raise AssertionError("existing overwrite must not be attempted")

            publisher = WebDavPublisher(NonTransactionalClient(webdav))
            report = publisher.publish(
                "/books/Book - Author.epub",
                epub,
                manifest(UpdateDecision.SAFE_APPEND),
                expected_old_epub_hash=sha256_bytes(old_epub_bytes),
                expected_old_manifest_hash=sha256_bytes(old_manifest_bytes),
            )

            self.assertEqual(report["status"], "pending")
            self.assertIn("transactional WebDAV support", report["reason"])
            self.assertEqual(remote_epub.read_bytes(), old_epub_bytes)
            self.assertEqual(remote_manifest.read_bytes(), old_manifest_bytes)

    def test_safe_append_concurrent_write_between_hash_check_and_put_goes_pending(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav = root / "webdav"
            (webdav / "books").mkdir(parents=True)
            target_path = "/books/Book - Author.epub"
            manifest_path = "/books/Book - Author.hermes.json"
            remote_epub = webdav / "books/Book - Author.epub"
            remote_manifest = webdav / "books/Book - Author.hermes.json"
            old_epub_bytes = b"old-epub"
            old_manifest_bytes = b'{"old":true}'
            concurrent_epub_bytes = b"concurrent-epub"
            concurrent_manifest_bytes = b'{"concurrent":true}'
            remote_epub.write_bytes(old_epub_bytes)
            remote_manifest.write_bytes(old_manifest_bytes)
            epub = root / "candidate.epub"
            epub.write_bytes(b"new-epub")

            class RacingTargetPutClient(LocalWebDavClient):
                def __init__(self, client_root):
                    super().__init__(client_root)
                    self.mutated = False

                def _mutate_remote_once(self):
                    if not self.mutated:
                        self.mutated = True
                        remote_epub.write_bytes(concurrent_epub_bytes)
                        remote_manifest.write_bytes(concurrent_manifest_bytes)

                def put(self, path, data):
                    if path == target_path and data == b"new-epub":
                        self._mutate_remote_once()
                    return super().put(path, data)

                def put_if_match(self, path, data, etag):
                    if path == target_path and data == b"new-epub":
                        self._mutate_remote_once()
                    return super().put_if_match(path, data, etag)

            publisher = WebDavPublisher(RacingTargetPutClient(webdav))
            report = publisher.publish(
                target_path,
                epub,
                manifest(UpdateDecision.SAFE_APPEND),
                expected_old_epub_hash=sha256_bytes(old_epub_bytes),
                expected_old_manifest_hash=sha256_bytes(old_manifest_bytes),
            )

            self.assertEqual(report["status"], "pending")
            self.assertEqual(remote_epub.read_bytes(), concurrent_epub_bytes)
            self.assertEqual(remote_manifest.read_bytes(), concurrent_manifest_bytes)
            self.assertTrue((webdav / "books/.pending/Book - Author/candidate.epub").exists())

    def test_safe_append_target_only_race_after_target_put_rolls_back_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav = root / "webdav"
            (webdav / "books").mkdir(parents=True)
            target_path = "/books/Book - Author.epub"
            manifest_path = "/books/Book - Author.hermes.json"
            remote_epub = webdav / "books/Book - Author.epub"
            remote_manifest = webdav / "books/Book - Author.hermes.json"
            old_epub_bytes = b"old-epub"
            old_manifest_bytes = b'{"old":true}'
            concurrent_epub_bytes = b"target-only-concurrent-epub"
            remote_epub.write_bytes(old_epub_bytes)
            remote_manifest.write_bytes(old_manifest_bytes)
            epub = root / "candidate.epub"
            epub.write_bytes(b"new-epub")

            class TargetRaceBeforeManifestClient(LocalWebDavClient):
                def put_if_match(self, path, data, etag):
                    if path == manifest_path and data != old_manifest_bytes:
                        remote_epub.write_bytes(concurrent_epub_bytes)
                    return super().put_if_match(path, data, etag)

            publisher = WebDavPublisher(TargetRaceBeforeManifestClient(webdav))
            report = publisher.publish(
                target_path,
                epub,
                manifest(UpdateDecision.SAFE_APPEND),
                expected_old_epub_hash=sha256_bytes(old_epub_bytes),
                expected_old_manifest_hash=sha256_bytes(old_manifest_bytes),
            )

            self.assertEqual(report["status"], "pending")
            self.assertEqual(remote_epub.read_bytes(), concurrent_epub_bytes)
            self.assertEqual(remote_manifest.read_bytes(), old_manifest_bytes)
            self.assertTrue((webdav / "books/.pending/Book - Author/candidate.epub").exists())

    def test_safe_append_rollback_does_not_overwrite_concurrent_writer_after_manifest_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            webdav = root / "webdav"
            (webdav / "books").mkdir(parents=True)
            target_path = "/books/Book - Author.epub"
            manifest_path = "/books/Book - Author.hermes.json"
            remote_epub = webdav / "books/Book - Author.epub"
            remote_manifest = webdav / "books/Book - Author.hermes.json"
            old_epub_bytes = b"old-epub"
            old_manifest_bytes = b'{"old":true}'
            concurrent_manifest_bytes = b'{"concurrent":true}'
            remote_epub.write_bytes(old_epub_bytes)
            remote_manifest.write_bytes(old_manifest_bytes)
            epub = root / "candidate.epub"
            epub.write_bytes(b"new-epub")

            class ManifestConflictAfterTargetPutClient(LocalWebDavClient):
                def put(self, path, data):
                    if path == target_path and data == b"new-epub":
                        super().put(path, data)
                        return None
                    if path == manifest_path and data != old_manifest_bytes:
                        remote_manifest.write_bytes(concurrent_manifest_bytes)
                        raise RuntimeError("manifest changed concurrently")
                    return super().put(path, data)

                def put_if_match(self, path, data, etag):
                    if path == manifest_path and data != old_manifest_bytes:
                        remote_manifest.write_bytes(concurrent_manifest_bytes)
                    return super().put_if_match(path, data, etag)

            publisher = WebDavPublisher(ManifestConflictAfterTargetPutClient(webdav))
            report = publisher.publish(
                target_path,
                epub,
                manifest(UpdateDecision.SAFE_APPEND),
                expected_old_epub_hash=sha256_bytes(old_epub_bytes),
                expected_old_manifest_hash=sha256_bytes(old_manifest_bytes),
            )

            self.assertEqual(report["status"], "pending")
            self.assertEqual(remote_epub.read_bytes(), old_epub_bytes)
            self.assertEqual(remote_manifest.read_bytes(), concurrent_manifest_bytes)
            self.assertTrue((webdav / "books/.pending/Book - Author/candidate.epub").exists())

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

                def put_if_match(self, path, data, etag):
                    if path == "/books/Book - Author.epub" and data == b"new-epub":
                        self.epub_put_seen = True
                    if (
                        path == "/books/Book - Author.hermes.json"
                        and self.epub_put_seen
                        and not self.failed_once
                    ):
                        self.failed_once = True
                        raise RuntimeError("injected manifest PUT failure")
                    return super().put_if_match(path, data, etag)

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

    def test_http_webdav_client_supports_verified_live_publish_paths(self):
        client = HttpWebDavClient("https://dav.example/root")

        self.assertTrue(client.supports_new_publish)
        self.assertTrue(client.supports_existing_overwrite)

    def test_http_webdav_client_conditional_puts_send_precondition_headers(self):
        captured = []
        original_urlopen = urllib.request.urlopen

        class FakeResponse:
            headers = {"ETag": '"new-etag"'}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b""

        def fake_urlopen(req, timeout):
            captured.append(
                (
                    req.get_method(),
                    req.full_url,
                    req.get_header("If-none-match"),
                    req.get_header("If-match"),
                )
            )
            return FakeResponse()

        try:
            urllib.request.urlopen = fake_urlopen
            client = HttpWebDavClient("https://dav.example/root")
            client.put_if_absent("/books/book.epub", b"new")
            client.put_if_match("/books/book.epub", b"updated", '"old-etag"')
        finally:
            urllib.request.urlopen = original_urlopen

        self.assertEqual(
            captured,
            [
                ("PUT", "https://dav.example/root/books/book.epub", "*", None),
                ("PUT", "https://dav.example/root/books/book.epub", None, '"old-etag"'),
            ],
        )

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
