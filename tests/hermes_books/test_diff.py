import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.hermes_books.diff import compare_for_update
from scripts.hermes_books.inspect import inspect_epub
from scripts.hermes_books.models import BookManifest, UpdateDecision
from tests.hermes_books.helpers import make_epub, reverse_spine_chapters


def rewrite_chapter(epub_path: Path, chapter_path: str, replace: tuple[str, str]) -> None:
    with zipfile.ZipFile(epub_path, "r") as source:
        entries = {name: source.read(name) for name in source.namelist()}

    full_path = f"EPUB/{chapter_path}"
    html = entries[full_path].decode("utf-8")
    html = html.replace(replace[0], replace[1])
    entries[full_path] = html.encode("utf-8")

    with zipfile.ZipFile(epub_path, "w") as target:
        for name, content in entries.items():
            target.writestr(name, content)


def add_image(epub_path: Path, href: str, data: bytes) -> None:
    with zipfile.ZipFile(epub_path, "r") as source:
        entries = {name: source.read(name) for name in source.namelist()}

    opf_path = "EPUB/content.opf"
    opf = entries[opf_path].decode("utf-8")
    item_id = Path(href).stem.replace("-", "_")
    item = f'<item href="{href}" id="{item_id}" media-type="image/jpeg" />'
    if item not in opf:
        opf = opf.replace("</manifest>", f"    {item}\n  </manifest>")
    entries[opf_path] = opf.encode("utf-8")
    entries[f"EPUB/{href}"] = data

    with zipfile.ZipFile(epub_path, "w") as target:
        for name, content in entries.items():
            target.writestr(name, content)


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

    def test_swapped_existing_chapters_in_large_book_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            chapters = [(f"第{idx}章", f"正文 {idx}") for idx in range(1, 101)]
            swapped = chapters.copy()
            swapped[0], swapped[1] = swapped[1], swapped[0]
            old = inspect_epub(make_epub(root / "old.epub", chapters=chapters))
            new = inspect_epub(make_epub(root / "new.epub", chapters=swapped))

            result = compare_for_update(manifest(), manifest(), old, new)

            self.assertEqual(result.decision, UpdateDecision.BLOCKED_RISKY)
            self.assertIn("existing chapter prefix changed", result.reasons)
            self.assertIn("chapter 1 fingerprint changed", result.reasons)
            self.assertIn("chapter 2 fingerprint changed", result.reasons)

    def test_spine_only_reorder_with_unchanged_manifest_order_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = inspect_epub(
                make_epub(root / "old.epub", chapters=[("第一章", "A"), ("第二章", "B")])
            )
            new_path = make_epub(root / "new.epub", chapters=[("第一章", "A"), ("第二章", "B")])
            reverse_spine_chapters(new_path)
            new = inspect_epub(new_path)

            result = compare_for_update(manifest(), manifest(), old, new)

            self.assertEqual(result.decision, UpdateDecision.BLOCKED_RISKY)
            self.assertIn("existing chapter prefix changed", result.reasons)

    def test_existing_prefix_href_or_item_id_drift_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = inspect_epub(
                make_epub(
                    root / "old.epub",
                    chapters=[("第一章", "same body")],
                    chapter_file_names=["chapters/old.xhtml"],
                )
            )
            new = inspect_epub(
                make_epub(
                    root / "new.epub",
                    chapters=[("第一章", "same body")],
                    chapter_file_names=["chapters/new.xhtml"],
                )
            )

            result = compare_for_update(manifest(), manifest(), old, new)

            self.assertEqual(result.decision, UpdateDecision.BLOCKED_RISKY)
            self.assertIn("chapter 1 href changed", result.reasons)

    def test_one_changed_existing_chapter_is_blocked_even_when_most_match(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            chapters = [(f"第{idx}章", f"正文 {idx}") for idx in range(1, 101)]
            changed = chapters.copy()
            changed[0] = ("第1章", "正文 changed")
            old = inspect_epub(make_epub(root / "old.epub", chapters=chapters))
            new = inspect_epub(make_epub(root / "new.epub", chapters=changed))

            result = compare_for_update(manifest(), manifest(), old, new)

            self.assertEqual(result.decision, UpdateDecision.BLOCKED_RISKY)
            self.assertIn("existing chapter prefix changed", result.reasons)
            self.assertIn("chapter 1 fingerprint changed", result.reasons)

    def test_canonical_id_mismatch_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = inspect_epub(make_epub(root / "old.epub", chapters=[("第一章", "A")]))
            new = inspect_epub(make_epub(root / "new.epub", chapters=[("第一章", "A")]))
            new_manifest = manifest()
            new_manifest.canonical_id = "other::author"

            result = compare_for_update(manifest(), new_manifest, old, new)

            self.assertEqual(result.decision, UpdateDecision.BLOCKED_RISKY)
            self.assertIn("canonical_id mismatch", result.reasons)

    def test_old_zero_chapter_epub_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = inspect_epub(make_epub(root / "old.epub", chapters=[]))
            new = inspect_epub(make_epub(root / "new.epub", chapters=[("第一章", "A")]))

            result = compare_for_update(manifest(), manifest(), old, new)

            self.assertEqual(result.decision, UpdateDecision.BLOCKED_RISKY)
            self.assertIn("old EPUB has no comparable chapters", result.reasons)

    def test_title_only_heading_only_change_with_same_body_is_safe_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = inspect_epub(make_epub(root / "old.epub", chapters=[("第一章", "same body")]))
            new = inspect_epub(
                make_epub(root / "new.epub", title="Book Revised", chapters=[("改题", "same body")])
            )

            result = compare_for_update(manifest(), manifest(title="Book Revised"), old, new)

            self.assertEqual(result.decision, UpdateDecision.SAFE_METADATA)

    def test_same_text_with_changed_paragraph_structure_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = inspect_epub(make_epub(root / "old.epub", chapters=[("第一章", "AB")]))
            new_path = make_epub(root / "new.epub", chapters=[("第一章", "AB")])
            rewrite_chapter(new_path, "chapters/ch0001.xhtml", ("<p>AB</p>", "<p>A</p><p>B</p>"))
            new = inspect_epub(new_path)

            self.assertEqual(old.chapters[0].fingerprint, new.chapters[0].fingerprint)
            self.assertNotEqual(
                old.chapters[0].structure_fingerprint,
                new.chapters[0].structure_fingerprint,
            )

            result = compare_for_update(manifest(), manifest(), old, new)

            self.assertEqual(result.decision, UpdateDecision.BLOCKED_RISKY)
            self.assertIn("chapter 1 structure changed", result.reasons)

    def test_same_text_with_changed_reader_anchor_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old_path = make_epub(root / "old.epub", chapters=[("第一章", "same body")])
            new_path = make_epub(root / "new.epub", chapters=[("第一章", "same body")])
            rewrite_chapter(old_path, "chapters/ch0001.xhtml", ("<p>same body</p>", '<p id="p1">same body</p>'))
            rewrite_chapter(new_path, "chapters/ch0001.xhtml", ("<p>same body</p>", '<p id="p2">same body</p>'))
            old = inspect_epub(old_path)
            new = inspect_epub(new_path)

            self.assertEqual(old.chapters[0].fingerprint, new.chapters[0].fingerprint)
            self.assertNotEqual(
                old.chapters[0].structure_fingerprint,
                new.chapters[0].structure_fingerprint,
            )

            result = compare_for_update(manifest(), manifest(), old, new)

            self.assertEqual(result.decision, UpdateDecision.BLOCKED_RISKY)
            self.assertIn("chapter 1 structure changed", result.reasons)

    def test_same_text_with_changed_in_chapter_heading_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old_path = make_epub(root / "old.epub", chapters=[("第一章", "same body")])
            new_path = make_epub(root / "new.epub", chapters=[("第一章", "same body")])
            rewrite_chapter(old_path, "chapters/ch0001.xhtml", ("</p>", "</p><h3>Old section</h3>"))
            rewrite_chapter(new_path, "chapters/ch0001.xhtml", ("</p>", "</p><h3>New section</h3>"))
            old = inspect_epub(old_path)
            new = inspect_epub(new_path)

            self.assertNotEqual(old.chapters[0].fingerprint, new.chapters[0].fingerprint)
            self.assertNotEqual(
                old.chapters[0].structure_fingerprint,
                new.chapters[0].structure_fingerprint,
            )

            result = compare_for_update(manifest(), manifest(), old, new)

            self.assertEqual(result.decision, UpdateDecision.BLOCKED_RISKY)
            self.assertIn("chapter 1 fingerprint changed", result.reasons)

    def test_same_text_with_changed_image_reference_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old_path = make_epub(root / "old.epub", chapters=[("第一章", "same body")])
            new_path = make_epub(root / "new.epub", chapters=[("第一章", "same body")])
            add_image(old_path, "images/old.jpg", b"old image")
            add_image(new_path, "images/new.jpg", b"old image")
            rewrite_chapter(old_path, "chapters/ch0001.xhtml", ("</p>", '</p><img src="../images/old.jpg"/>'))
            rewrite_chapter(new_path, "chapters/ch0001.xhtml", ("</p>", '</p><img src="../images/new.jpg"/>'))
            old = inspect_epub(old_path)
            new = inspect_epub(new_path)

            self.assertEqual(old.chapters[0].fingerprint, new.chapters[0].fingerprint)
            self.assertNotEqual(
                old.chapters[0].structure_fingerprint,
                new.chapters[0].structure_fingerprint,
            )

            result = compare_for_update(manifest(), manifest(), old, new)

            self.assertEqual(result.decision, UpdateDecision.BLOCKED_RISKY)
            self.assertIn("chapter 1 structure changed", result.reasons)

    def test_same_text_with_changed_image_bytes_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old_path = make_epub(root / "old.epub", chapters=[("第一章", "same body")])
            new_path = make_epub(root / "new.epub", chapters=[("第一章", "same body")])
            add_image(old_path, "images/plate.jpg", b"old image")
            add_image(new_path, "images/plate.jpg", b"new image")
            rewrite_chapter(old_path, "chapters/ch0001.xhtml", ("</p>", '</p><img src="../images/plate.jpg"/>'))
            rewrite_chapter(new_path, "chapters/ch0001.xhtml", ("</p>", '</p><img src="../images/plate.jpg"/>'))
            old = inspect_epub(old_path)
            new = inspect_epub(new_path)

            self.assertEqual(old.chapters[0].fingerprint, new.chapters[0].fingerprint)
            self.assertEqual(
                old.chapters[0].structure_fingerprint,
                new.chapters[0].structure_fingerprint,
            )
            self.assertNotEqual(
                old.chapters[0].resource_fingerprint,
                new.chapters[0].resource_fingerprint,
            )

            result = compare_for_update(manifest(), manifest(), old, new)

            self.assertEqual(result.decision, UpdateDecision.BLOCKED_RISKY)
            self.assertIn("chapter 1 resources changed", result.reasons)

    def test_same_text_with_fragmented_image_href_and_changed_image_bytes_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old_path = make_epub(root / "old.epub", chapters=[("第一章", "same body")])
            new_path = make_epub(root / "new.epub", chapters=[("第一章", "same body")])
            add_image(old_path, "images/plate.jpg", b"old image")
            add_image(new_path, "images/plate.jpg", b"new image")
            rewrite_chapter(old_path, "chapters/ch0001.xhtml", ("</p>", '</p><img src="../images/plate.jpg#fig1"/>'))
            rewrite_chapter(new_path, "chapters/ch0001.xhtml", ("</p>", '</p><img src="../images/plate.jpg#fig1"/>'))
            old = inspect_epub(old_path)
            new = inspect_epub(new_path)

            self.assertEqual(old.chapters[0].fingerprint, new.chapters[0].fingerprint)
            self.assertNotEqual(
                old.chapters[0].resource_fingerprint,
                new.chapters[0].resource_fingerprint,
            )

            result = compare_for_update(manifest(), manifest(), old, new)

            self.assertEqual(result.decision, UpdateDecision.BLOCKED_RISKY)
            self.assertIn("chapter 1 resources changed", result.reasons)

    def test_same_text_with_changed_css_resource_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = inspect_epub(
                make_epub(root / "old.epub", chapters=[("第一章", "same body")], css="p { line-height: 1.4; }")
            )
            new = inspect_epub(
                make_epub(root / "new.epub", chapters=[("第一章", "same body")], css="p { line-height: 1.8; }")
            )

            self.assertEqual(old.chapters[0].fingerprint, new.chapters[0].fingerprint)
            self.assertNotEqual(
                old.chapters[0].resource_fingerprint,
                new.chapters[0].resource_fingerprint,
            )

            result = compare_for_update(manifest(), manifest(), old, new)

            self.assertEqual(result.decision, UpdateDecision.BLOCKED_RISKY)
            self.assertIn("chapter 1 resources changed", result.reasons)


if __name__ == "__main__":
    unittest.main()
