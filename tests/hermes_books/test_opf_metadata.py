import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from scripts.hermes_books.config import MetadataEnrichmentConfig
from scripts.hermes_books.metadata import MetadataDecision, MetadataEnricher, MetadataEvidence, MetadataResolution
from scripts.hermes_books.opf_metadata import apply_metadata_to_epub
from tests.hermes_books.helpers import make_epub


def _report(decisions):
    evidence = [
        MetadataEvidence("store-1", "store", "https://example.test/books/1", {"title": "标准书名"}),
    ]
    return MetadataEnricher(MetadataEnrichmentConfig()).decide(
        evidence,
        MetadataResolution(decisions=decisions),
    )


def _opf_root(epub_path: Path):
    with zipfile.ZipFile(epub_path) as archive:
        root = ElementTree.fromstring(archive.read("EPUB/content.opf"))
    return root


def _texts(root, local_name: str) -> list[str]:
    return [
        element.text or ""
        for element in root.iter()
        if element.tag.endswith(f"}}{local_name}") or element.tag == local_name
    ]


class OpfMetadataTests(unittest.TestCase):
    def test_apply_metadata_updates_opf_without_replacing_primary_identifier(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_epub(root / "source.epub", title="旧书名", identifier="urn:test:stable")
            report = _report(
                [
                    MetadataDecision("title", "旧书名", "标准书名", "apply", 0.95, ["store-1"], "title match"),
                    MetadataDecision("authors", ["旧作者"], ["新作者"], "apply", 0.95, ["store-1"], "author match"),
                    MetadataDecision("publisher", "", "小学馆", "apply", 0.95, ["store-1"], "publisher match"),
                    MetadataDecision("isbn", "", "9780000000000", "apply", 0.95, ["store-1"], "isbn match"),
                    MetadataDecision("description", "", "故事简介", "apply", 0.95, ["store-1"], "description match"),
                    MetadataDecision("subjects", [], ["轻小说", "校园"], "apply", 0.95, ["store-1"], "subject match"),
                    MetadataDecision("series", "", "系列名", "apply", 0.95, ["store-1"], "series match"),
                    MetadataDecision("volume", "", 2, "apply", 0.95, ["store-1"], "volume match"),
                    MetadataDecision("illustrators", [], ["画师"], "apply", 0.95, ["store-1"], "illustrator match"),
                ]
            )

            output = apply_metadata_to_epub(source, root / "out.epub", report)
            opf = _opf_root(output)
            opf_text = ElementTree.tostring(opf, encoding="unicode")

            self.assertIn("标准书名", _texts(opf, "title"))
            self.assertIn("新作者", _texts(opf, "creator"))
            self.assertIn("小学馆", _texts(opf, "publisher"))
            self.assertIn("故事简介", _texts(opf, "description"))
            self.assertIn("轻小说", _texts(opf, "subject"))
            self.assertIn("校园", _texts(opf, "subject"))
            self.assertIn("urn:test:stable", _texts(opf, "identifier"))
            self.assertIn("9780000000000", _texts(opf, "identifier"))
            self.assertIn("系列名", opf_text)
            self.assertIn("画师", opf_text)
            self.assertIn("volume", opf_text)

    def test_apply_metadata_cover_preserves_existing_cover_and_uses_unique_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_epub(root / "source.epub", cover_file_name="images/hermes-metadata-cover.jpg")
            report = _report(
                [
                    MetadataDecision("cover", "", "https://example.test/cover.jpg", "apply", 0.95, ["store-1"], "cover match"),
                ]
            )

            output = apply_metadata_to_epub(source, root / "out.epub", report, cover_bytes=b"new cover bytes")

            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertIn("EPUB/images/hermes-metadata-cover.jpg", names)
                self.assertIn("EPUB/images/hermes-metadata-cover-2.jpg", names)
                self.assertEqual(archive.read("EPUB/images/hermes-metadata-cover-2.jpg"), b"new cover bytes")
                opf_text = archive.read("EPUB/content.opf").decode("utf-8")
            self.assertIn("cover-image", opf_text)
            self.assertIn("hermes-metadata-cover-2.jpg", opf_text)


if __name__ == "__main__":
    unittest.main()
