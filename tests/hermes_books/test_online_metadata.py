import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.hermes_books.config import MetadataEnrichmentConfig, OnlineEnrichmentConfig
from scripts.hermes_books.metadata import (
    MetadataClues,
    MetadataDecision,
    MetadataEnricher,
    MetadataReport,
)
from scripts.hermes_books.online_metadata import (
    DeterministicMetadataReasoner,
    OnlineCoverFetcher,
    OnlineMetadataProvider,
    _redact_url,
)


GOOGLE_PAYLOAD = {
    "items": [
        {
            "id": "google-1",
            "volumeInfo": {
                "title": "测试小说",
                "authors": ["测试作者"],
                "publisher": "测试出版社",
                "publishedDate": "2025-01-02",
                "description": "<p>一本用于测试的小说。</p>",
                "categories": ["轻小说", "幻想"],
                "industryIdentifiers": [
                    {"type": "ISBN_13", "identifier": "9780306406157"}
                ],
                "imageLinks": {"large": "https://books.google.com/cover.jpg"},
                "canonicalVolumeLink": "https://books.google.com/books?id=google-1",
            },
        }
    ]
}

OPEN_LIBRARY_PAYLOAD = {
    "docs": [
        {
            "key": "/works/OL1W",
            "title": "测试小说",
            "author_name": ["测试作者"],
            "publisher": ["测试出版社"],
            "isbn": ["9780306406157"],
            "subject": ["轻小说", "幻想"],
            "cover_i": 12345,
            "first_publish_year": 2025,
        }
    ]
}


class OnlineMetadataTests(unittest.TestCase):
    def test_provider_and_reasoner_build_traceable_consensus(self):
        with tempfile.TemporaryDirectory() as td:
            config = OnlineEnrichmentConfig(enabled=True)

            def fetch(url: str):
                if "googleapis.com" in url:
                    return GOOGLE_PAYLOAD
                if "openlibrary.org" in url:
                    return OPEN_LIBRARY_PAYLOAD
                raise AssertionError(url)

            provider = OnlineMetadataProvider(config, Path(td), fetch_json=fetch)
            clues = MetadataClues(
                title="测试小说",
                author="测试作者",
                existing_metadata={"missing_cover": True},
            )
            evidence = provider.search(clues)
            resolution = DeterministicMetadataReasoner().resolve(clues, evidence)
            report = MetadataEnricher(MetadataEnrichmentConfig()).decide(evidence, resolution)

            self.assertEqual(len(evidence), 2)
            self.assertEqual({item.source for item in evidence}, {"google-books", "open-library"})
            applied = {decision.field: decision for decision in report.applied_decisions}
            self.assertEqual(applied["publisher"].new_value, "测试出版社")
            self.assertEqual(len(applied["publisher"].evidence_ids), 2)
            self.assertEqual(applied["isbn"].new_value, "9780306406157")
            self.assertEqual(applied["description"].new_value, "一本用于测试的小说。")
            self.assertEqual(applied["cover"].new_value, "https://books.google.com/cover.jpg")

    def test_existing_metadata_is_preserved_for_review(self):
        config = OnlineEnrichmentConfig(enabled=True, sources="google-books")
        provider = OnlineMetadataProvider(config, Path("unused"), fetch_json=lambda _url: GOOGLE_PAYLOAD)
        clues = MetadataClues(
            title="测试小说",
            author="测试作者",
            existing_metadata={"description": "已有简介", "missing_cover": False},
        )

        evidence = provider.search(clues)
        resolution = DeterministicMetadataReasoner().resolve(clues, evidence)

        decisions = {decision.field: decision for decision in resolution.decisions}
        self.assertEqual(decisions["description"].action, "review")
        self.assertEqual(decisions["cover"].action, "review")
        self.assertEqual(decisions["isbn"].action, "review")

    def test_low_identity_results_are_filtered(self):
        payload = {
            "items": [
                {
                    "id": "wrong",
                    "volumeInfo": {"title": "完全不同的书", "authors": ["另一作者"]},
                }
            ]
        }
        config = OnlineEnrichmentConfig(enabled=True, sources="google-books")
        provider = OnlineMetadataProvider(config, Path("unused"), fetch_json=lambda _url: payload)

        evidence = provider.search(MetadataClues(title="测试小说", author="测试作者"))

        self.assertEqual(evidence, [])

    def test_api_keys_are_redacted_from_cached_request_urls(self):
        redacted = _redact_url(
            "https://www.googleapis.com/books/v1/volumes?q=book&key=secret-value"
        )

        self.assertIn("key=REDACTED", redacted)
        self.assertNotIn("secret-value", redacted)

    def test_invalid_isbn_is_not_emitted_as_evidence(self):
        payload = {
            "items": [
                {
                    "id": "book",
                    "volumeInfo": {
                        "title": "测试小说",
                        "authors": ["测试作者"],
                        "industryIdentifiers": [
                            {"type": "ISBN_13", "identifier": "9781234567890"}
                        ],
                    },
                }
            ]
        }
        config = OnlineEnrichmentConfig(enabled=True, sources="google-books")
        provider = OnlineMetadataProvider(config, Path("unused"), fetch_json=lambda _url: payload)

        evidence = provider.search(MetadataClues(title="测试小说", author="测试作者"))

        self.assertEqual(len(evidence), 1)
        self.assertNotIn("isbn", evidence[0].facts)

    def test_cover_fetcher_uses_validated_cache_and_rejects_untrusted_hosts(self):
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td)
            config = OnlineEnrichmentConfig(enabled=True)
            fetcher = OnlineCoverFetcher(config, cache_dir)
            url = "https://covers.openlibrary.org/b/id/1-L.jpg?default=false"
            digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
            (cache_dir / f"cover-{digest}.bin").write_bytes(b"\xff\xd8\xffcached")
            report = MetadataReport(
                mode="aggressive",
                status="applied",
                applied_decisions=[
                    MetadataDecision("cover", "", url, "apply", 0.98, ["ol:1"], "match")
                ],
            )

            self.assertEqual(fetcher(report), b"\xff\xd8\xffcached")
            report.applied_decisions[0] = MetadataDecision(
                "cover",
                "",
                "https://evil.example/cover.jpg",
                "apply",
                0.98,
                ["evil:1"],
                "match",
            )
            with self.assertRaises(ValueError):
                fetcher(report)


if __name__ == "__main__":
    unittest.main()
