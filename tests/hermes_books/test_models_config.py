import json
import tempfile
import unittest
from pathlib import Path

from scripts.hermes_books.config import (
    HermesConfig,
    KOReaderMetadataLocation,
    MetadataEnrichmentMode,
    TextCleaningMode,
    TypographyMode,
)
from scripts.hermes_books.models import (
    AssetMode,
    BookJob,
    BookManifest,
    UpdateDecision,
    canonical_id_for,
    safe_slug,
)


class ModelsConfigTests(unittest.TestCase):
    def test_safe_slug_and_canonical_id_are_stable_for_chinese_titles(self):
        self.assertEqual(safe_slug(" 成功回避死亡结局 ", "addict"), "成功回避死亡结局 - addict")
        self.assertEqual(
            canonical_id_for(" 成功回避死亡结局 ", "Addict"),
            "成功回避死亡结局::addict",
        )

    def test_book_job_derives_target_paths(self):
        job = BookJob.from_input(
            input_path=Path("D:/Books/raw.txt"),
            title="某书",
            author="某作者",
            runs_root=Path("runs"),
        )
        self.assertEqual(job.input_format, "txt")
        self.assertEqual(job.target_slug, "某书 - 某作者")
        self.assertEqual(job.webdav_target_path, "/books/某书 - 某作者.epub")
        self.assertEqual(job.asset_mode, AssetMode.BALANCED)

    def test_manifest_round_trip_json(self):
        manifest = BookManifest(
            canonical_id="book::author",
            title="Book",
            author="Author",
            opf_identifier="urn:hermes:book-author",
            source_hash="source",
            output_hash="output",
            update_decision=UpdateDecision.SAFE_APPEND,
        )
        raw = manifest.to_json()
        loaded = BookManifest.from_json(raw)
        self.assertEqual(loaded.canonical_id, "book::author")
        self.assertEqual(loaded.update_decision, UpdateDecision.SAFE_APPEND)
        self.assertEqual(json.loads(raw)["schema_version"], 2)

    def test_config_defaults_and_yaml_override(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "hermes-books.yaml"
            cfg_path.write_text(
                "webdav:\n"
                "  base_url: https://dav.example.test\n"
                "asset_enrichment:\n"
                "  mode: aggressive\n",
                encoding="utf-8",
            )
            cfg = HermesConfig.load(cfg_path)
        self.assertEqual(cfg.webdav.base_url, "https://dav.example.test")
        self.assertEqual(cfg.webdav.books_path, "/books")
        self.assertEqual(cfg.asset_enrichment.mode, AssetMode.AGGRESSIVE)
        self.assertEqual(cfg.update_policy.chapter_fingerprint_threshold, 0.98)
        self.assertEqual(cfg.typography.mode, TypographyMode.NORMALIZE)

    def test_loads_metadata_and_koreader_config(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "hermes-books.yaml"
            cfg_path.write_text(
                "metadata_enrichment:\n"
                "  mode: \"aggressive\"\n"
                "  auto_apply_min_confidence: 0.91\n"
                "  require_evidence_url: false\n"
                "  write_cover: false\n"
                "koreader:\n"
                "  metadata_location: \"hashdocsettings\"\n",
                encoding="utf-8",
            )

            cfg = HermesConfig.load(cfg_path)

        self.assertEqual(cfg.metadata_enrichment.mode, MetadataEnrichmentMode.AGGRESSIVE)
        self.assertEqual(cfg.metadata_enrichment.auto_apply_min_confidence, 0.91)
        self.assertFalse(cfg.metadata_enrichment.require_evidence_url)
        self.assertFalse(cfg.metadata_enrichment.write_cover)
        self.assertEqual(cfg.koreader.metadata_location, KOReaderMetadataLocation.HASHDOCSETTINGS)

    def test_rejects_non_block_hashdocsettings_policy(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "hermes-books.yaml"
            cfg_path.write_text(
                "koreader:\n"
                "  metadata_location: \"hashdocsettings\"\n"
                "  hashdocsettings_policy: \"keep\"\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                HermesConfig.load(cfg_path)

    def test_loads_text_cleaning_config(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "hermes-books.yaml"
            cfg_path.write_text(
                "text_cleaning:\n"
                "  mode: \"off\"\n"
                "  max_input_chars: 50000\n"
                "  max_estimated_cost_cny: 0.25\n",
                encoding="utf-8",
            )

            cfg = HermesConfig.load(cfg_path)

        self.assertEqual(cfg.text_cleaning.mode, TextCleaningMode.OFF)
        self.assertEqual(cfg.text_cleaning.max_input_chars, 50000)
        self.assertEqual(cfg.text_cleaning.max_estimated_cost_cny, 0.25)

    def test_loads_typography_and_online_enrichment_config(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "hermes-books.yaml"
            cfg_path.write_text(
                "typography:\n"
                "  mode: audit-only\n"
                "  block_on_failure: false\n"
                "online_enrichment:\n"
                "  enabled: true\n"
                "  sources: google-books\n"
                "  min_identity_score: 0.9\n",
                encoding="utf-8",
            )

            cfg = HermesConfig.load(cfg_path)

        self.assertEqual(cfg.typography.mode, TypographyMode.AUDIT_ONLY)
        self.assertFalse(cfg.typography.block_on_failure)
        self.assertTrue(cfg.online_enrichment.enabled)
        self.assertEqual(cfg.online_enrichment.sources, "google-books")
        self.assertEqual(cfg.online_enrichment.min_identity_score, 0.9)

    def test_example_config_is_loadable_with_inline_comments(self):
        cfg = HermesConfig.load(Path("config/hermes-books.example.yaml"))

        self.assertEqual(cfg.typography.mode, TypographyMode.NORMALIZE)
        self.assertTrue(cfg.online_enrichment.enabled)


if __name__ == "__main__":
    unittest.main()
