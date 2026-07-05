# Hermes Book Intake MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local TXT/EPUB intake pipeline that produces normalized EPUB3 files, enriches assets, blocks risky updates, and publishes safe updates to the WebDAV remote master.

**Architecture:** Add a focused `scripts/hermes_books` package instead of expanding the existing one-file scripts. The package wraps existing TXT conversion helpers where useful, then routes every draft or original EPUB through a shared inspection, asset, diff, and publish flow. Tests use the Python standard library `unittest` plus temporary directories and fake WebDAV/asset providers so the plan remains runnable without external services.

**Tech Stack:** Python 3.11+, `ebooklib`, `charset-normalizer`, stdlib `zipfile`, `urllib.request`, `unittest`, existing scripts under `scripts/txt2epub` and `scripts/epub_fix`.

---

## Scope Check

This plan implements the first Hermes Book Intake MVP only:

- Local TXT input.
- Local EPUB input.
- TXT draft EPUB creation followed by the shared EPUB path.
- EPUB inspection and normalization reports.
- Deterministic asset enrichment with injectable network providers.
- Append-safe update decisions.
- WebDAV remote-master publishing with backup and pending paths.
- CLI entry point usable by Hermes.

This plan does not implement UMD/JAR, generic book-source search, Kindle-side auto-update, or direct `.sdr` mutation.

## File Structure

- Create `scripts/hermes_books/__init__.py`: package exports.
- Create `scripts/hermes_books/models.py`: dataclasses, enums, JSON helpers, stable IDs.
- Create `scripts/hermes_books/config.py`: YAML-lite config loading with defaults and env references.
- Create `scripts/hermes_books/sources.py`: local file source and run workspace setup.
- Create `scripts/hermes_books/build.py`: TXT draft EPUB builder and EPUB normalization entry.
- Create `scripts/hermes_books/inspect.py`: EPUB inspection, chapter/image/CSS metadata extraction, report models.
- Create `scripts/hermes_books/assets.py`: asset candidate model, injectable providers, cover/illustration adoption rules.
- Create `scripts/hermes_books/diff.py`: append-safe comparison from old/new inspections and manifests.
- Create `scripts/hermes_books/publish.py`: WebDAV client abstraction, HTTP implementation, local fake implementation, backup/pending publish.
- Create `scripts/hermes_books/intake.py`: orchestrator and CLI.
- Create `config/hermes-books.example.yaml`: documented example config.
- Create `tests/hermes_books/helpers.py`: test EPUB and fake provider helpers.
- Create tests under `tests/hermes_books/`.

## Task 1: Core Models And Config

**Files:**
- Create: `scripts/hermes_books/__init__.py`
- Create: `scripts/hermes_books/models.py`
- Create: `scripts/hermes_books/config.py`
- Test: `tests/hermes_books/test_models_config.py`

- [ ] **Step 1: Write failing tests for IDs, paths, manifest JSON, and config defaults**

Create `tests/hermes_books/test_models_config.py`:

```python
import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts.hermes_books.config import HermesConfig
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
        self.assertEqual(json.loads(raw)["schema_version"], 1)

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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify they fail because modules do not exist**

Run:

```powershell
python -m unittest tests.hermes_books.test_models_config -v
```

Expected: failure with `ModuleNotFoundError: No module named 'scripts.hermes_books'`.

- [ ] **Step 3: Implement package exports**

Create `scripts/hermes_books/__init__.py`:

```python
"""Hermes book intake package."""

from .models import BookJob, BookManifest, UpdateDecision

__all__ = ["BookJob", "BookManifest", "UpdateDecision"]
```

- [ ] **Step 4: Implement models**

Create `scripts/hermes_books/models.py`:

```python
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class AssetMode(str, Enum):
    OFF = "off"
    COVER_ONLY = "cover-only"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class UpdateDecision(str, Enum):
    SAFE_APPEND = "SAFE_APPEND"
    SAFE_METADATA = "SAFE_METADATA"
    REVIEW_MINOR = "REVIEW_MINOR"
    BLOCKED_RISKY = "BLOCKED_RISKY"
    NEW_BOOK = "NEW_BOOK"


def _normalise_identity(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[《》「」『』\"'`]", "", value)
    return value


def canonical_id_for(title: str, author: str) -> str:
    return f"{_normalise_identity(title)}::{_normalise_identity(author)}"


def safe_slug(title: str, author: str) -> str:
    raw = f"{title.strip()} - {author.strip()}"
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw).strip(" .")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class BookJob:
    id: str
    input_path: Path
    input_format: str
    title: str
    author: str
    target_slug: str
    webdav_target_path: str
    runs_root: Path
    run_dir: Path
    asset_mode: AssetMode = AssetMode.BALANCED

    @classmethod
    def from_input(
        cls,
        input_path: Path,
        title: str,
        author: str,
        runs_root: Path,
        asset_mode: AssetMode = AssetMode.BALANCED,
        books_path: str = "/books",
    ) -> "BookJob":
        suffix = input_path.suffix.lower().lstrip(".")
        input_format = "txt" if suffix in {"txt", "text"} else suffix
        job_id = uuid.uuid4().hex
        slug = safe_slug(title, author)
        books_path = "/" + books_path.strip("/")
        return cls(
            id=job_id,
            input_path=input_path,
            input_format=input_format,
            title=title,
            author=author,
            target_slug=slug,
            webdav_target_path=f"{books_path}/{slug}.epub",
            runs_root=runs_root,
            run_dir=runs_root / job_id,
            asset_mode=asset_mode,
        )


@dataclass
class ChapterInfo:
    index: int
    title: str
    href: str
    fingerprint: str
    text_chars: int


@dataclass
class ImageInfo:
    href: str
    media_type: str
    size_bytes: int
    role: str = "unknown"


@dataclass
class QualityIssue:
    severity: str
    code: str
    message: str
    href: str = ""


@dataclass
class BookManifest:
    canonical_id: str
    title: str
    author: str
    opf_identifier: str
    source_hash: str
    output_hash: str
    update_decision: UpdateDecision = UpdateDecision.NEW_BOOK
    schema_version: int = 1
    chapter_map: list[dict[str, Any]] = field(default_factory=list)
    image_inventory: list[dict[str, Any]] = field(default_factory=list)
    quality_report: dict[str, Any] = field(default_factory=dict)
    asset_report: dict[str, Any] = field(default_factory=dict)
    previous_versions: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> str:
        def convert(value: Any) -> Any:
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, Path):
                return str(value)
            return value

        return json.dumps(asdict(self), ensure_ascii=False, indent=2, default=convert)

    @classmethod
    def from_json(cls, raw: str) -> "BookManifest":
        data = json.loads(raw)
        data["update_decision"] = UpdateDecision(data.get("update_decision", "NEW_BOOK"))
        return cls(**data)
```

- [ ] **Step 5: Implement config loader**

Create `scripts/hermes_books/config.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import AssetMode


@dataclass(frozen=True)
class WebDavConfig:
    base_url: str = ""
    books_path: str = "/books"
    username_env: str = "WEBDAV_USERNAME"
    password_env: str = "WEBDAV_PASSWORD"


@dataclass(frozen=True)
class PipelineConfig:
    require_epubcheck: bool = True
    keep_runs: bool = True
    output_profile: str = "koreader"
    language: str = "zh"


@dataclass(frozen=True)
class UpdatePolicyConfig:
    default: str = "append-safe"
    chapter_fingerprint_threshold: float = 0.98
    block_on_chapter_count_decrease: bool = True
    block_on_reordered_existing_chapters: bool = True


@dataclass(frozen=True)
class AssetEnrichmentConfig:
    mode: AssetMode = AssetMode.BALANCED
    auto_cover_min_confidence: float = 0.85
    auto_insert_illustration_min_confidence: float = 0.92
    require_source_url: bool = True
    preserve_original_images: bool = True


@dataclass(frozen=True)
class HermesConfig:
    webdav: WebDavConfig = WebDavConfig()
    pipeline: PipelineConfig = PipelineConfig()
    update_policy: UpdatePolicyConfig = UpdatePolicyConfig()
    asset_enrichment: AssetEnrichmentConfig = AssetEnrichmentConfig()

    @classmethod
    def load(cls, path: Path | None) -> "HermesConfig":
        if path is None or not path.exists():
            return cls()
        data = _parse_simple_yaml(path.read_text(encoding="utf-8"))
        webdav = WebDavConfig(**{**WebDavConfig().__dict__, **data.get("webdav", {})})
        pipeline = PipelineConfig(**{**PipelineConfig().__dict__, **data.get("pipeline", {})})
        update_policy = UpdatePolicyConfig(
            **{**UpdatePolicyConfig().__dict__, **data.get("update_policy", {})}
        )
        asset_data: dict[str, Any] = {**AssetEnrichmentConfig().__dict__, **data.get("asset_enrichment", {})}
        asset_data["mode"] = AssetMode(asset_data["mode"])
        asset_enrichment = AssetEnrichmentConfig(**asset_data)
        return cls(webdav, pipeline, update_policy, asset_enrichment)


def _parse_scalar(value: str) -> Any:
    value = value.strip().strip('"').strip("'")
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _parse_simple_yaml(raw: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    section = ""
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" ") and line.endswith(":"):
            section = line[:-1].strip()
            result[section] = {}
            continue
        if section and ":" in line:
            key, value = line.split(":", 1)
            result[section][key.strip()] = _parse_scalar(value)
    return result
```

- [ ] **Step 6: Run tests and verify they pass**

Run:

```powershell
python -m unittest tests.hermes_books.test_models_config -v
```

Expected: 4 tests pass.

- [ ] **Step 7: Commit**

```powershell
git add scripts/hermes_books tests/hermes_books/test_models_config.py
git commit -m "feat: add Hermes book intake core models"
```

## Task 2: Local Source And Run Workspace

**Files:**
- Create: `scripts/hermes_books/sources.py`
- Test: `tests/hermes_books/test_sources.py`

- [ ] **Step 1: Write failing source/workspace tests**

Create `tests/hermes_books/test_sources.py`:

```python
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
```

- [ ] **Step 2: Run tests and verify they fail because `sources.py` is missing**

Run:

```powershell
python -m unittest tests.hermes_books.test_sources -v
```

Expected: failure importing `scripts.hermes_books.sources`.

- [ ] **Step 3: Implement local source and workspace setup**

Create `scripts/hermes_books/sources.py`:

```python
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .models import BookJob, sha256_file


@dataclass(frozen=True)
class RunPaths:
    raw_dir: Path
    draft_dir: Path
    normalized_dir: Path
    reports_dir: Path


@dataclass(frozen=True)
class SourceSnapshot:
    raw_path: Path
    source_hash: str


def prepare_run_workspace(job: BookJob) -> RunPaths:
    raw_dir = job.run_dir / "raw"
    draft_dir = job.run_dir / "draft"
    normalized_dir = job.run_dir / "normalized"
    reports_dir = job.run_dir / "reports"
    for path in (raw_dir, draft_dir, normalized_dir, reports_dir):
        path.mkdir(parents=True, exist_ok=True)
    return RunPaths(raw_dir, draft_dir, normalized_dir, reports_dir)


class LocalFileSource:
    def __init__(self, job: BookJob) -> None:
        self.job = job

    def snapshot(self) -> SourceSnapshot:
        if not self.job.input_path.is_file():
            raise FileNotFoundError(f"Input file not found: {self.job.input_path}")
        paths = prepare_run_workspace(self.job)
        raw_path = paths.raw_dir / self.job.input_path.name
        shutil.copy2(self.job.input_path, raw_path)
        return SourceSnapshot(raw_path=raw_path, source_hash=sha256_file(raw_path))
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
python -m unittest tests.hermes_books.test_sources -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```powershell
git add scripts/hermes_books/sources.py tests/hermes_books/test_sources.py
git commit -m "feat: add local file source snapshots"
```

## Task 3: TXT Draft EPUB Builder

**Files:**
- Create: `scripts/hermes_books/build.py`
- Test: `tests/hermes_books/test_build_txt.py`

- [ ] **Step 1: Write failing TXT draft builder tests**

Create `tests/hermes_books/test_build_txt.py`:

```python
import tempfile
import unittest
from pathlib import Path

from ebooklib import epub

from scripts.hermes_books.build import build_draft_from_txt
from scripts.hermes_books.models import BookJob
from scripts.hermes_books.sources import LocalFileSource, prepare_run_workspace


class TxtBuildTests(unittest.TestCase):
    def test_txt_builds_draft_epub_then_can_be_read_by_ebooklib(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            txt = root / "novel.txt"
            txt.write_text(
                "第一章 开始\n"
                "这是第一段。\n\n"
                "第二章 继续\n"
                "这是第二段。\n",
                encoding="utf-8",
            )
            job = BookJob.from_input(txt, "测试小说", "作者", root / "runs")
            snapshot = LocalFileSource(job).snapshot()
            paths = prepare_run_workspace(job)

            draft = build_draft_from_txt(job, snapshot.raw_path, paths.draft_dir)

            self.assertTrue(draft.exists())
            book = epub.read_epub(str(draft))
            self.assertEqual(book.get_metadata("DC", "title")[0][0], "测试小说")
            html_names = sorted(item.file_name for item in book.get_items() if item.file_name.endswith(".xhtml"))
            self.assertIn("chapters/ch0001.xhtml", html_names)
            self.assertIn("chapters/ch0002.xhtml", html_names)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```powershell
python -m unittest tests.hermes_books.test_build_txt -v
```

Expected: failure importing `build_draft_from_txt`.

- [ ] **Step 3: Implement TXT draft builder using existing TXT helpers with stable chapter filenames**

Create `scripts/hermes_books/build.py`:

```python
from __future__ import annotations

import html
import re
import uuid
from pathlib import Path

from ebooklib import epub

from scripts.txt2epub.pipeline import (
    STANDARD_CSS,
    detect_chapters,
    filter_garbage,
    merge_hard_linebreaks,
    normalize_paragraphs,
    read_text,
)

from .models import BookJob, canonical_id_for


def _stable_identifier(job: BookJob) -> str:
    return "urn:hermes:" + re.sub(r"[^a-zA-Z0-9]+", "-", canonical_id_for(job.title, job.author)).strip("-")


def _chapter_file(index: int) -> str:
    return f"chapters/ch{index:04d}.xhtml"


def build_draft_from_txt(job: BookJob, raw_txt_path: Path, draft_dir: Path) -> Path:
    text = read_text(str(raw_txt_path))
    chapters = detect_chapters(text)
    chapters = [ch for ch in chapters if any(line.strip() for line in ch["content_lines"])]
    for ch in chapters:
        ch["content_lines"] = normalize_paragraphs(
            merge_hard_linebreaks(filter_garbage(ch["content_lines"]))
        )

    book = epub.EpubBook()
    book.set_identifier(_stable_identifier(job))
    book.set_title(job.title)
    book.set_language("zh")
    book.add_author(job.author)

    css_item = epub.EpubItem(
        uid="standard-css",
        file_name="styles/standard.css",
        media_type="text/css",
        content=STANDARD_CSS.encode("utf-8"),
    )
    book.add_item(css_item)

    spine: list[object] = ["nav"]
    toc: list[object] = []
    for idx, ch in enumerate(chapters, start=1):
        title = str(ch["title"])
        body = [f"<h2 id=\"title\">{html.escape(title)}</h2>"]
        for para_idx, line in enumerate(ch["content_lines"], start=1):
            stripped = line.strip()
            if stripped:
                body.append(f"<p id=\"p{para_idx:04d}\">{html.escape(stripped)}</p>")
        chapter = epub.EpubHtml(title=title, file_name=_chapter_file(idx), lang="zh")
        chapter.content = (
            "<?xml version='1.0' encoding='utf-8'?>\n"
            "<!DOCTYPE html>\n"
            "<html xmlns='http://www.w3.org/1999/xhtml' xml:lang='zh'>"
            "<head><title>{}</title><link rel='stylesheet' type='text/css' href='../styles/standard.css'/></head>"
            "<body>{}</body></html>"
        ).format(html.escape(title), "\n".join(body)).encode("utf-8")
        chapter.add_item(css_item)
        book.add_item(chapter)
        spine.append(chapter)
        toc.append(epub.Link(chapter.file_name, title, f"ch{idx:04d}"))

    book.toc = toc
    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    draft_dir.mkdir(parents=True, exist_ok=True)
    output = draft_dir / f"{job.target_slug}.draft.epub"
    epub.write_epub(str(output), book)
    return output


def normalize_existing_epub(job: BookJob, raw_epub_path: Path, normalized_dir: Path) -> Path:
    normalized_dir.mkdir(parents=True, exist_ok=True)
    output = normalized_dir / f"{job.target_slug}.normalized.epub"
    output.write_bytes(raw_epub_path.read_bytes())
    return output
```

- [ ] **Step 4: Run TXT builder tests**

Run:

```powershell
python -m unittest tests.hermes_books.test_build_txt -v
```

Expected: 1 test passes.

- [ ] **Step 5: Commit**

```powershell
git add scripts/hermes_books/build.py tests/hermes_books/test_build_txt.py
git commit -m "feat: build draft EPUB from TXT"
```

## Task 4: EPUB Inspection And Quality Reports

**Files:**
- Create: `scripts/hermes_books/inspect.py`
- Create: `tests/hermes_books/helpers.py`
- Test: `tests/hermes_books/test_inspect.py`

- [ ] **Step 1: Write helper for test EPUBs**

Create `tests/hermes_books/helpers.py`:

```python
from pathlib import Path

from ebooklib import epub


def make_epub(path: Path, title: str = "Book", author: str = "Author", chapters: list[tuple[str, str]] | None = None, css: str = "p { text-indent: 2em; }") -> Path:
    chapters = chapters or [("第一章", "第一章正文"), ("第二章", "第二章正文")]
    book = epub.EpubBook()
    book.set_identifier("urn:test:book-author")
    book.set_title(title)
    book.set_language("zh")
    book.add_author(author)
    css_item = epub.EpubItem(uid="style", file_name="styles/style.css", media_type="text/css", content=css.encode("utf-8"))
    book.add_item(css_item)
    spine: list[object] = ["nav"]
    toc: list[object] = []
    for idx, (chapter_title, text) in enumerate(chapters, start=1):
        chapter = epub.EpubHtml(title=chapter_title, file_name=f"chapters/ch{idx:04d}.xhtml", lang="zh")
        chapter.content = f"<html xmlns='http://www.w3.org/1999/xhtml'><body><h2>{chapter_title}</h2><p>{text}</p></body></html>".encode("utf-8")
        chapter.add_item(css_item)
        book.add_item(chapter)
        spine.append(chapter)
        toc.append(epub.Link(chapter.file_name, chapter_title, f"ch{idx:04d}"))
    book.toc = toc
    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(path), book)
    return path
```

- [ ] **Step 2: Write failing inspection tests**

Create `tests/hermes_books/test_inspect.py`:

```python
import tempfile
import unittest
from pathlib import Path

from scripts.hermes_books.inspect import inspect_epub, write_quality_report
from tests.hermes_books.helpers import make_epub


class InspectTests(unittest.TestCase):
    def test_inspect_extracts_chapters_identifier_css_issues_and_cover_status(self):
        with tempfile.TemporaryDirectory() as td:
            epub_path = make_epub(Path(td) / "book.epub", css="p { font-size: 16px; }")
            report = inspect_epub(epub_path)

            self.assertEqual(report.title, "Book")
            self.assertEqual(report.author, "Author")
            self.assertEqual(report.opf_identifier, "urn:test:book-author")
            self.assertEqual(len(report.chapters), 2)
            self.assertTrue(report.missing_cover)
            self.assertTrue(any(issue.code == "CSS_ABSOLUTE_FONT_SIZE" for issue in report.issues))

    def test_write_quality_report_contains_human_summary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            epub_path = make_epub(root / "book.epub")
            report = inspect_epub(epub_path)
            out = write_quality_report(report, root / "quality-report.md")
            text = out.read_text(encoding="utf-8")
            self.assertIn("EPUB quality report", text)
            self.assertIn("Chapters: 2", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run tests and verify they fail because inspection module is missing**

Run:

```powershell
python -m unittest tests.hermes_books.test_inspect -v
```

Expected: import failure for `scripts.hermes_books.inspect`.

- [ ] **Step 4: Implement EPUB inspection**

Create `scripts/hermes_books/inspect.py`:

```python
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import ebooklib
from ebooklib import epub

from .models import ChapterInfo, ImageInfo, QualityIssue


@dataclass
class EpubInspection:
    path: Path
    title: str
    author: str
    opf_identifier: str
    chapters: list[ChapterInfo] = field(default_factory=list)
    images: list[ImageInfo] = field(default_factory=list)
    issues: list[QualityIssue] = field(default_factory=list)
    missing_cover: bool = True


def _metadata_first(book: epub.EpubBook, name: str, default: str = "") -> str:
    values = book.get_metadata("DC", name)
    if not values:
        return default
    return str(values[0][0])


def _normalise_text(raw: str) -> str:
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = re.sub(r"\s+", "", raw)
    return raw


def _fingerprint(raw_html: bytes) -> tuple[str, int]:
    text = _normalise_text(raw_html.decode("utf-8", errors="replace"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), len(text)


def _css_issues(item_name: str, css: str) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    if re.search(r"font-size\s*:\s*\d+(\.\d+)?\s*(px|pt)\b", css, re.I):
        issues.append(QualityIssue("HIGH", "CSS_ABSOLUTE_FONT_SIZE", "CSS uses px/pt font-size", item_name))
    if re.search(r"line-height\s*:\s*0\.\d+", css, re.I):
        issues.append(QualityIssue("MEDIUM", "CSS_LOW_LINE_HEIGHT", "CSS line-height is below 1.0", item_name))
    return issues


def inspect_epub(path: Path) -> EpubInspection:
    book = epub.read_epub(str(path))
    identifier_values = book.get_metadata("DC", "identifier")
    opf_identifier = str(identifier_values[0][0]) if identifier_values else ""
    report = EpubInspection(
        path=path,
        title=_metadata_first(book, "title", path.stem),
        author=_metadata_first(book, "creator", "Unknown"),
        opf_identifier=opf_identifier,
    )

    for idx, item in enumerate(book.get_items_of_type(ebooklib.ITEM_DOCUMENT), start=1):
        name = str(item.file_name)
        if name.endswith("nav.xhtml") or name.endswith("nav.html"):
            continue
        fp, chars = _fingerprint(item.get_content())
        title = getattr(item, "title", "") or name
        report.chapters.append(ChapterInfo(idx, title, name, fp, chars))

    for item in book.get_items():
        media_type = str(getattr(item, "media_type", ""))
        if media_type.startswith("image/"):
            role = "cover" if "cover" in str(item.file_name).lower() else "unknown"
            if role == "cover":
                report.missing_cover = False
            report.images.append(ImageInfo(str(item.file_name), media_type, len(item.get_content()), role))
        if media_type == "text/css":
            report.issues.extend(_css_issues(str(item.file_name), item.get_content().decode("utf-8", errors="replace")))

    if not report.chapters:
        report.issues.append(QualityIssue("HIGH", "NO_CHAPTERS", "No readable chapter documents found"))
    if report.missing_cover:
        report.issues.append(QualityIssue("MEDIUM", "MISSING_COVER", "No cover image found"))
    return report


def write_quality_report(report: EpubInspection, output_path: Path) -> Path:
    lines = [
        "# EPUB quality report",
        "",
        f"Title: {report.title}",
        f"Author: {report.author}",
        f"Identifier: {report.opf_identifier}",
        f"Chapters: {len(report.chapters)}",
        f"Images: {len(report.images)}",
        f"Missing cover: {report.missing_cover}",
        "",
        "## Issues",
    ]
    if report.issues:
        for issue in report.issues:
            lines.append(f"- [{issue.severity}] {issue.code}: {issue.message} {issue.href}".rstrip())
    else:
        lines.append("- None")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path
```

- [ ] **Step 5: Run inspection tests**

Run:

```powershell
python -m unittest tests.hermes_books.test_inspect -v
```

Expected: 2 tests pass.

- [ ] **Step 6: Commit**

```powershell
git add scripts/hermes_books/inspect.py tests/hermes_books/helpers.py tests/hermes_books/test_inspect.py
git commit -m "feat: inspect EPUB quality metadata"
```

## Task 5: Asset Enrichment

**Files:**
- Create: `scripts/hermes_books/assets.py`
- Test: `tests/hermes_books/test_assets.py`

- [ ] **Step 1: Write failing asset enrichment tests using a fake provider**

Create `tests/hermes_books/test_assets.py`:

```python
import tempfile
import unittest
from pathlib import Path

from scripts.hermes_books.assets import AssetCandidate, AssetEnricher, AssetReport
from scripts.hermes_books.config import AssetEnrichmentConfig
from scripts.hermes_books.models import AssetMode
from scripts.hermes_books.inspect import inspect_epub
from tests.hermes_books.helpers import make_epub


class FakeProvider:
    def candidates(self, title: str, author: str, role: str):
        return [
            AssetCandidate(
                role=role,
                source_url="https://assets.example/cover.jpg",
                local_path=Path("cover.jpg"),
                width=1600,
                height=2400,
                confidence=0.93,
                reason="fake high confidence cover",
            )
        ]


class AssetTests(unittest.TestCase):
    def test_cover_is_auto_selected_when_missing_and_confident(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            epub_path = make_epub(root / "book.epub")
            report = inspect_epub(epub_path)
            enricher = AssetEnricher(AssetEnrichmentConfig(mode=AssetMode.BALANCED), FakeProvider())

            asset_report = enricher.plan("Book", "Author", report, root)

            self.assertEqual(asset_report.auto_adopted[0].role, "cover")
            self.assertEqual(asset_report.auto_adopted[0].confidence, 0.93)

    def test_low_confidence_candidate_goes_to_pending(self):
        class LowProvider:
            def candidates(self, title: str, author: str, role: str):
                return [AssetCandidate(role, "https://assets.example/x.jpg", Path("x.jpg"), 500, 700, 0.5, "weak")]

        with tempfile.TemporaryDirectory() as td:
            report = inspect_epub(make_epub(Path(td) / "book.epub"))
            enricher = AssetEnricher(AssetEnrichmentConfig(mode=AssetMode.BALANCED), LowProvider())
            asset_report = enricher.plan("Book", "Author", report, Path(td))
            self.assertEqual(asset_report.auto_adopted, [])
            self.assertEqual(asset_report.pending[0].confidence, 0.5)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify they fail because `assets.py` is missing**

Run:

```powershell
python -m unittest tests.hermes_books.test_assets -v
```

Expected: import failure.

- [ ] **Step 3: Implement asset enrichment models and planner**

Create `scripts/hermes_books/assets.py`:

```python
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from .config import AssetEnrichmentConfig
from .inspect import EpubInspection
from .models import AssetMode


@dataclass
class AssetCandidate:
    role: str
    source_url: str
    local_path: Path
    width: int
    height: int
    confidence: float
    reason: str


@dataclass
class AssetReport:
    auto_adopted: list[AssetCandidate] = field(default_factory=list)
    pending: list[AssetCandidate] = field(default_factory=list)
    missing_roles: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        def convert(value):
            if isinstance(value, Path):
                return str(value)
            return value

        return json.dumps(asdict(self), ensure_ascii=False, indent=2, default=convert)


class AssetProvider(Protocol):
    def candidates(self, title: str, author: str, role: str) -> list[AssetCandidate]:
        ...


class GoogleBooksCoverProvider:
    def candidates(self, title: str, author: str, role: str) -> list[AssetCandidate]:
        if role != "cover":
            return []
        query = urllib.parse.urlencode({"q": f'intitle:"{title}" inauthor:"{author}"'})
        url = f"https://www.googleapis.com/books/v1/volumes?{query}"
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return []
        candidates: list[AssetCandidate] = []
        for item in data.get("items", [])[:3]:
            image_links = item.get("volumeInfo", {}).get("imageLinks", {})
            cover_url = image_links.get("extraLarge") or image_links.get("large") or image_links.get("thumbnail")
            if not cover_url:
                continue
            candidates.append(
                AssetCandidate(
                    role="cover",
                    source_url=cover_url.replace("http://", "https://"),
                    local_path=Path(""),
                    width=0,
                    height=0,
                    confidence=0.86,
                    reason="Google Books title/author cover candidate",
                )
            )
        return candidates


class AssetEnricher:
    def __init__(self, config: AssetEnrichmentConfig, provider: AssetProvider | None = None) -> None:
        self.config = config
        self.provider = provider or GoogleBooksCoverProvider()

    def plan(self, title: str, author: str, inspection: EpubInspection, cache_dir: Path) -> AssetReport:
        report = AssetReport()
        if self.config.mode == AssetMode.OFF:
            return report

        roles: list[str] = []
        if inspection.missing_cover and self.config.mode in {AssetMode.COVER_ONLY, AssetMode.BALANCED, AssetMode.AGGRESSIVE}:
            roles.append("cover")
        if self.config.mode == AssetMode.AGGRESSIVE:
            roles.append("illustration")

        for role in roles:
            candidates = self.provider.candidates(title, author, role)
            if not candidates:
                report.missing_roles.append(role)
                continue
            threshold = (
                self.config.auto_cover_min_confidence
                if role == "cover"
                else self.config.auto_insert_illustration_min_confidence
            )
            for candidate in candidates:
                if self.config.require_source_url and not candidate.source_url:
                    report.pending.append(candidate)
                elif candidate.confidence >= threshold:
                    report.auto_adopted.append(candidate)
                else:
                    report.pending.append(candidate)
        return report
```

- [ ] **Step 4: Run asset tests**

Run:

```powershell
python -m unittest tests.hermes_books.test_assets -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```powershell
git add scripts/hermes_books/assets.py tests/hermes_books/test_assets.py
git commit -m "feat: plan EPUB asset enrichment"
```

## Task 6: Append-Safe Diff

**Files:**
- Create: `scripts/hermes_books/diff.py`
- Test: `tests/hermes_books/test_diff.py`

- [ ] **Step 1: Write failing diff tests**

Create `tests/hermes_books/test_diff.py`:

```python
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
            old = inspect_epub(make_epub(root / "old.epub", chapters=[("第一章", "A"), ("第二章", "B")]))
            new = inspect_epub(make_epub(root / "new.epub", chapters=[("第一章", "A"), ("第二章", "B"), ("第三章", "C")]))

            result = compare_for_update(manifest(), manifest(), old, new)

            self.assertEqual(result.decision, UpdateDecision.SAFE_APPEND)

    def test_removed_chapter_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = inspect_epub(make_epub(root / "old.epub", chapters=[("第一章", "A"), ("第二章", "B")]))
            new = inspect_epub(make_epub(root / "new.epub", chapters=[("第一章", "A")]))

            result = compare_for_update(manifest(), manifest(), old, new)

            self.assertEqual(result.decision, UpdateDecision.BLOCKED_RISKY)
            self.assertIn("chapter count decreased", result.reasons[0])

    def test_metadata_only_change_is_safe_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = inspect_epub(make_epub(root / "old.epub", chapters=[("第一章", "A")]))
            new = inspect_epub(make_epub(root / "new.epub", title="Book Revised", chapters=[("第一章", "A")]))

            result = compare_for_update(manifest(), manifest(), old, new)

            self.assertEqual(result.decision, UpdateDecision.SAFE_METADATA)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify they fail because `diff.py` is missing**

Run:

```powershell
python -m unittest tests.hermes_books.test_diff -v
```

Expected: import failure.

- [ ] **Step 3: Implement append-safe comparison**

Create `scripts/hermes_books/diff.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field

from .inspect import EpubInspection
from .models import BookManifest, UpdateDecision


@dataclass
class UpdateDiff:
    decision: UpdateDecision
    reasons: list[str] = field(default_factory=list)
    matched_existing_chapters: int = 0
    old_chapter_count: int = 0
    new_chapter_count: int = 0


def compare_for_update(
    old_manifest: BookManifest,
    new_manifest: BookManifest,
    old: EpubInspection,
    new: EpubInspection,
    fingerprint_threshold: float = 0.98,
) -> UpdateDiff:
    if old_manifest.canonical_id != new_manifest.canonical_id:
        return UpdateDiff(UpdateDecision.BLOCKED_RISKY, ["canonical_id mismatch"])
    if len(new.chapters) < len(old.chapters):
        return UpdateDiff(
            UpdateDecision.BLOCKED_RISKY,
            ["chapter count decreased"],
            old_chapter_count=len(old.chapters),
            new_chapter_count=len(new.chapters),
        )

    matched = 0
    changed: list[str] = []
    for idx, old_chapter in enumerate(old.chapters):
        new_chapter = new.chapters[idx]
        if old_chapter.fingerprint == new_chapter.fingerprint:
            matched += 1
        else:
            changed.append(f"chapter {idx + 1} fingerprint changed")

    ratio = matched / len(old.chapters) if old.chapters else 0.0
    base = UpdateDiff(
        UpdateDecision.SAFE_APPEND,
        matched_existing_chapters=matched,
        old_chapter_count=len(old.chapters),
        new_chapter_count=len(new.chapters),
    )
    if ratio < fingerprint_threshold:
        return UpdateDiff(
            UpdateDecision.BLOCKED_RISKY,
            [f"existing chapter fingerprint ratio {ratio:.2f} below {fingerprint_threshold:.2f}", *changed],
            matched_existing_chapters=matched,
            old_chapter_count=len(old.chapters),
            new_chapter_count=len(new.chapters),
        )
    if len(new.chapters) == len(old.chapters):
        base.decision = UpdateDecision.SAFE_METADATA
        base.reasons.append("existing chapter fingerprints unchanged")
    else:
        base.reasons.append("new chapters appended after stable prefix")
    return base
```

- [ ] **Step 4: Run diff tests**

Run:

```powershell
python -m unittest tests.hermes_books.test_diff -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```powershell
git add scripts/hermes_books/diff.py tests/hermes_books/test_diff.py
git commit -m "feat: add append-safe EPUB diff"
```

## Task 7: WebDAV Publisher

**Files:**
- Create: `scripts/hermes_books/publish.py`
- Test: `tests/hermes_books/test_publish.py`

- [ ] **Step 1: Write failing publisher tests with local fake WebDAV**

Create `tests/hermes_books/test_publish.py`:

```python
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
```

- [ ] **Step 2: Run tests and verify they fail because publisher is missing**

Run:

```powershell
python -m unittest tests.hermes_books.test_publish -v
```

Expected: import failure.

- [ ] **Step 3: Implement WebDAV publisher and local fake client**

Create `scripts/hermes_books/publish.py`:

```python
from __future__ import annotations

import base64
import json
import os
import posixpath
import urllib.request
from pathlib import Path
from typing import Protocol

from .models import BookManifest, UpdateDecision


class WebDavClient(Protocol):
    def exists(self, path: str) -> bool:
        ...

    def get(self, path: str) -> bytes:
        ...

    def put(self, path: str, data: bytes) -> None:
        ...

    def mkdir(self, path: str) -> None:
        ...


class LocalWebDavClient:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, path: str) -> Path:
        return self.root / path.strip("/")

    def exists(self, path: str) -> bool:
        return self._path(path).exists()

    def get(self, path: str) -> bytes:
        return self._path(path).read_bytes()

    def put(self, path: str, data: bytes) -> None:
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def mkdir(self, path: str) -> None:
        self._path(path).mkdir(parents=True, exist_ok=True)


class HttpWebDavClient:
    def __init__(self, base_url: str, username: str = "", password: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password

    def _request(self, path: str, method: str, data: bytes | None = None) -> bytes:
        req = urllib.request.Request(self.base_url + "/" + path.strip("/"), data=data, method=method)
        if self.username:
            token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            req.add_header("Authorization", f"Basic {token}")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise FileNotFoundError(path) from exc
            raise

    def exists(self, path: str) -> bool:
        try:
            self._request(path, "HEAD")
            return True
        except FileNotFoundError:
            return False

    def get(self, path: str) -> bytes:
        return self._request(path, "GET")

    def put(self, path: str, data: bytes) -> None:
        self._request(path, "PUT", data)

    def mkdir(self, path: str) -> None:
        try:
            self._request(path, "MKCOL")
        except urllib.error.HTTPError as exc:
            if exc.code not in {405, 409}:
                raise


class WebDavPublisher:
    def __init__(self, client: WebDavClient) -> None:
        self.client = client

    def publish(self, target_epub_path: str, epub_path: Path, manifest: BookManifest) -> dict[str, str]:
        slug = Path(target_epub_path).stem
        manifest_path = target_epub_path[:-5] + ".hermes.json"
        decision = manifest.update_decision
        if decision in {UpdateDecision.BLOCKED_RISKY, UpdateDecision.REVIEW_MINOR}:
            pending_dir = posixpath.join(posixpath.dirname(target_epub_path), ".pending", slug)
            self.client.mkdir(pending_dir)
            self.client.put(posixpath.join(pending_dir, "candidate.epub"), epub_path.read_bytes())
            self.client.put(posixpath.join(pending_dir, "candidate.hermes.json"), manifest.to_json().encode("utf-8"))
            self.client.put(posixpath.join(pending_dir, "risk-report.md"), f"# Pending update\n\nDecision: {decision.value}\n".encode("utf-8"))
            return {"status": "pending", "path": pending_dir}

        if self.client.exists(target_epub_path):
            backup_dir = posixpath.join(posixpath.dirname(target_epub_path), ".backups", slug)
            self.client.mkdir(backup_dir)
            self.client.put(posixpath.join(backup_dir, "old.epub"), self.client.get(target_epub_path))
            if self.client.exists(manifest_path):
                self.client.put(posixpath.join(backup_dir, "old.hermes.json"), self.client.get(manifest_path))

        self.client.put(target_epub_path, epub_path.read_bytes())
        self.client.put(manifest_path, manifest.to_json().encode("utf-8"))
        return {"status": "published", "path": target_epub_path}
```

- [ ] **Step 4: Run publisher tests**

Run:

```powershell
python -m unittest tests.hermes_books.test_publish -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```powershell
git add scripts/hermes_books/publish.py tests/hermes_books/test_publish.py
git commit -m "feat: publish Hermes EPUBs to WebDAV"
```

## Task 8: Intake Orchestrator And CLI

**Files:**
- Modify: `scripts/hermes_books/intake.py`
- Test: `tests/hermes_books/test_intake.py`

- [ ] **Step 1: Write failing end-to-end intake tests**

Create `tests/hermes_books/test_intake.py`:

```python
import tempfile
import unittest
from pathlib import Path

from scripts.hermes_books.intake import run_intake
from scripts.hermes_books.publish import LocalWebDavClient
from tests.hermes_books.helpers import make_epub


class IntakeTests(unittest.TestCase):
    def test_txt_input_generates_reports_and_publishes_new_book(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            txt = root / "novel.txt"
            txt.write_text("第一章\n正文\n", encoding="utf-8")
            result = run_intake(
                input_path=txt,
                title="小说",
                author="作者",
                runs_root=root / "runs",
                webdav_client=LocalWebDavClient(root / "webdav"),
            )

            self.assertEqual(result.publish_report["status"], "published")
            self.assertTrue((root / "webdav/books/小说 - 作者.epub").exists())
            self.assertTrue((result.reports_dir / "quality-report.md").exists())
            self.assertTrue((result.reports_dir / "asset-report.json").exists())
            self.assertTrue((result.reports_dir / "publish-report.json").exists())

    def test_epub_input_uses_existing_epub_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_epub = make_epub(root / "source.epub")
            result = run_intake(
                input_path=source_epub,
                title="Book",
                author="Author",
                runs_root=root / "runs",
                webdav_client=LocalWebDavClient(root / "webdav"),
            )

            self.assertEqual(result.publish_report["status"], "published")
            self.assertTrue((root / "webdav/books/Book - Author.epub").exists())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify they fail because orchestrator is missing**

Run:

```powershell
python -m unittest tests.hermes_books.test_intake -v
```

Expected: import failure for `scripts.hermes_books.intake`.

- [ ] **Step 3: Implement orchestrator and CLI**

Create `scripts/hermes_books/intake.py`:

```python
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .assets import AssetEnricher
from .build import build_draft_from_txt, normalize_existing_epub
from .config import HermesConfig
from .diff import compare_for_update
from .inspect import inspect_epub, write_quality_report
from .models import BookJob, BookManifest, UpdateDecision, canonical_id_for, sha256_file
from .publish import HttpWebDavClient, WebDavClient, WebDavPublisher
from .sources import LocalFileSource, prepare_run_workspace


@dataclass
class IntakeResult:
    job: BookJob
    output_epub: Path
    manifest: BookManifest
    reports_dir: Path
    publish_report: dict[str, str]


def _manifest_from_inspection(job: BookJob, source_hash: str, output_epub: Path, inspection, decision: UpdateDecision) -> BookManifest:
    return BookManifest(
        canonical_id=canonical_id_for(job.title, job.author),
        title=job.title,
        author=job.author,
        opf_identifier=inspection.opf_identifier or f"urn:hermes:{canonical_id_for(job.title, job.author)}",
        source_hash=source_hash,
        output_hash=sha256_file(output_epub),
        update_decision=decision,
        chapter_map=[chapter.__dict__ for chapter in inspection.chapters],
        image_inventory=[image.__dict__ for image in inspection.images],
        quality_report={"issues": [issue.__dict__ for issue in inspection.issues]},
    )


def run_intake(
    input_path: Path,
    title: str,
    author: str,
    runs_root: Path = Path("runs"),
    config: HermesConfig | None = None,
    webdav_client: WebDavClient | None = None,
) -> IntakeResult:
    config = config or HermesConfig()
    job = BookJob.from_input(input_path, title, author, runs_root, config.asset_enrichment.mode, config.webdav.books_path)
    paths = prepare_run_workspace(job)
    snapshot = LocalFileSource(job).snapshot()

    if job.input_format == "txt":
        candidate = build_draft_from_txt(job, snapshot.raw_path, paths.draft_dir)
        output_epub = normalize_existing_epub(job, candidate, paths.normalized_dir)
    elif job.input_format == "epub":
        output_epub = normalize_existing_epub(job, snapshot.raw_path, paths.normalized_dir)
    else:
        raise ValueError(f"Unsupported input format for MVP: {job.input_format}")

    inspection = inspect_epub(output_epub)
    write_quality_report(inspection, paths.reports_dir / "quality-report.md")

    asset_report = AssetEnricher(config.asset_enrichment).plan(title, author, inspection, job.run_dir / "assets-cache")
    (paths.reports_dir / "asset-report.json").write_text(asset_report.to_json(), encoding="utf-8")

    decision = UpdateDecision.NEW_BOOK
    manifest_path = job.webdav_target_path[:-5] + ".hermes.json"
    if webdav_client and webdav_client.exists(manifest_path) and webdav_client.exists(job.webdav_target_path):
        old_manifest = BookManifest.from_json(webdav_client.get(manifest_path).decode("utf-8"))
        old_epub = paths.raw_dir / "old-remote.epub"
        old_epub.write_bytes(webdav_client.get(job.webdav_target_path))
        old_inspection = inspect_epub(old_epub)
        temp_manifest = _manifest_from_inspection(job, snapshot.source_hash, output_epub, inspection, UpdateDecision.NEW_BOOK)
        diff = compare_for_update(old_manifest, temp_manifest, old_inspection, inspection, config.update_policy.chapter_fingerprint_threshold)
        decision = diff.decision
        (paths.reports_dir / "update-diff.md").write_text(
            "# Update diff\n\n"
            f"Decision: {diff.decision.value}\n"
            f"Reasons: {', '.join(diff.reasons)}\n"
            f"Matched existing chapters: {diff.matched_existing_chapters}\n",
            encoding="utf-8",
        )

    manifest = _manifest_from_inspection(job, snapshot.source_hash, output_epub, inspection, decision)
    manifest.asset_report = json.loads(asset_report.to_json())
    manifest_file = paths.reports_dir / "manifest.json"
    manifest_file.write_text(manifest.to_json(), encoding="utf-8")

    if webdav_client is None:
        username = os.environ.get(config.webdav.username_env, "")
        password = os.environ.get(config.webdav.password_env, "")
        webdav_client = HttpWebDavClient(config.webdav.base_url, username, password)
    publish_report = WebDavPublisher(webdav_client).publish(job.webdav_target_path, output_epub, manifest)
    (paths.reports_dir / "publish-report.json").write_text(json.dumps(publish_report, ensure_ascii=False, indent=2), encoding="utf-8")

    return IntakeResult(job, output_epub, manifest, paths.reports_dir, publish_report)


def main() -> None:
    parser = argparse.ArgumentParser(description="Hermes local TXT/EPUB intake")
    parser.add_argument("input", help="Local TXT or EPUB input path")
    parser.add_argument("-t", "--title", required=True)
    parser.add_argument("-a", "--author", required=True)
    parser.add_argument("--config", default="config/hermes-books.yaml")
    parser.add_argument("--runs-root", default="runs")
    args = parser.parse_args()
    config = HermesConfig.load(Path(args.config))
    result = run_intake(Path(args.input), args.title, args.author, Path(args.runs_root), config)
    print(json.dumps({"output": str(result.output_epub), "publish": result.publish_report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run intake tests**

Run:

```powershell
python -m unittest tests.hermes_books.test_intake -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Run all Hermes tests**

Run:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

Expected: all Hermes tests pass.

- [ ] **Step 6: Commit**

```powershell
git add scripts/hermes_books tests/hermes_books
git commit -m "feat: orchestrate Hermes book intake"
```

## Task 9: Example Config And Usage Docs

**Files:**
- Create: `config/hermes-books.example.yaml`
- Modify: `README.md`
- Test: `python -m unittest discover -s tests -p "test_*.py" -v`

- [ ] **Step 1: Add example config**

Create `config/hermes-books.example.yaml`:

```yaml
webdav:
  base_url: "https://example.com/webdav"
  books_path: "/books"
  username_env: "WEBDAV_USERNAME"
  password_env: "WEBDAV_PASSWORD"

pipeline:
  require_epubcheck: true
  keep_runs: true
  output_profile: "koreader"
  language: "zh"

update_policy:
  default: "append-safe"
  chapter_fingerprint_threshold: 0.98
  block_on_chapter_count_decrease: true
  block_on_reordered_existing_chapters: true

asset_enrichment:
  mode: "balanced"
  auto_cover_min_confidence: 0.85
  auto_insert_illustration_min_confidence: 0.92
  require_source_url: true
  preserve_original_images: true
```

- [ ] **Step 2: Add README usage section**

Append this section to `README.md` after the existing “脚本” section:

```markdown
## Hermes Book Intake MVP

本地 TXT 或 EPUB 可以通过 Hermes intake 管线进入统一 EPUB3 处理流程：

```powershell
python scripts/hermes_books/intake.py "D:\Books\raw.txt" -t "书名" -a "作者" --config config/hermes-books.yaml
python scripts/hermes_books/intake.py "D:\Books\raw.epub" -t "书名" -a "作者" --config config/hermes-books.yaml
```

管线会在 `runs/<job-id>/` 下保留 raw、draft、normalized 和 reports。发布到 WebDAV 前会执行 append-safe 检查：旧章节稳定且只追加新章时覆盖 `/books/书名 - 作者.epub`，风险更新进入 `/books/.pending/`。
```

- [ ] **Step 3: Run all tests**

Run:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```powershell
git add README.md config/hermes-books.example.yaml
git commit -m "docs: document Hermes book intake usage"
```

## Task 10: Manual Smoke Test

**Files:**
- No new source files.
- Uses: `scripts/hermes_books/intake.py`

- [ ] **Step 1: Create a temporary TXT fixture**

Run:

```powershell
$tmp = New-Item -ItemType Directory -Force -Path "$env:TEMP\hermes-smoke"
@"
第一章 开始
这是第一章正文。

第二章 继续
这是第二章正文。
"@ | Set-Content -Encoding UTF8 -LiteralPath "$tmp\smoke.txt"
```

Expected: `$env:TEMP\hermes-smoke\smoke.txt` exists.

- [ ] **Step 2: Run local intake with fake WebDAV root by executing the Python API**

Run:

```powershell
@'
from pathlib import Path
from scripts.hermes_books.intake import run_intake
from scripts.hermes_books.publish import LocalWebDavClient

root = Path(r"%TEMP%").expanduser() / "hermes-smoke"
result = run_intake(
    input_path=root / "smoke.txt",
    title="Smoke Book",
    author="Hermes",
    runs_root=root / "runs",
    webdav_client=LocalWebDavClient(root / "webdav"),
)
print(result.output_epub)
print(result.publish_report)
'@.Replace("%TEMP%", $env:TEMP) | python -
```

Expected output includes `{'status': 'published', 'path': '/books/Smoke Book - Hermes.epub'}`.

- [ ] **Step 3: Verify smoke outputs**

Run:

```powershell
Test-Path "$env:TEMP\hermes-smoke\webdav\books\Smoke Book - Hermes.epub"
Test-Path "$env:TEMP\hermes-smoke\webdav\books\Smoke Book - Hermes.hermes.json"
Get-ChildItem "$env:TEMP\hermes-smoke\runs" -Recurse -Filter quality-report.md | Select-Object -First 1
```

Expected: both `Test-Path` commands print `True`, and one `quality-report.md` path is printed.

- [ ] **Step 4: Commit if smoke fixes were required**

If Task 10 required source or test edits, run:

```powershell
git add scripts tests README.md config
git commit -m "fix: stabilize Hermes intake smoke test"
```

If Task 10 required no edits, do not create a commit.

## Final Verification

- [ ] Run all tests:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

Expected: all tests pass.

- [ ] Run git status:

```powershell
git status --short
```

Expected: no unstaged source or test changes remain. Generated smoke files under `%TEMP%` are outside the repo.

## Spec Coverage Self-Review

- Local TXT input: Task 3 and Task 8.
- Local EPUB input: Task 8.
- TXT draft re-enters EPUB flow: Task 8 routes TXT through draft then `normalize_existing_epub`.
- EPUB inspection and quality reports: Task 4.
- Asset enrichment and candidate reports: Task 5 and Task 8.
- WebDAV `/books/` publish: Task 7 and Task 8.
- Append-safe update decisions: Task 6 and Task 8.
- Backup and pending directories: Task 7.
- Per-run reports and manifest: Task 8.
- Example config and usage docs: Task 9.
- Smoke verification: Task 10.
