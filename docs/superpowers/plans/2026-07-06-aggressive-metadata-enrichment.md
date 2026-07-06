# Aggressive Metadata Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add aggressive, evidence-backed EPUB metadata and cover writing while preserving KOReader progress association by stable path guards and `hashdocsettings` blocking.

**Architecture:** Add metadata evidence/resolution models plus an `MetadataEnricher` orchestration module, an OPF rewrite module, config knobs, and intake integration. The implementation remains provider-agnostic: tests inject static providers/reasoners, while real web/LLM providers can be added later.

**Tech Stack:** Python 3.12 stdlib, `ebooklib`, `zipfile`, `xml.etree.ElementTree`, current `unittest` test suite.

---

### Task 1: Config Surface

**Files:**
- Modify: `scripts/hermes_books/config.py`
- Modify: `config/hermes-books.example.yaml`
- Test: `tests/hermes_books/test_models_config.py`

- [ ] **Step 1: Write failing config tests**

Add tests that load `metadata_enrichment` and `koreader` config:

```python
def test_loads_metadata_and_koreader_config(self):
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "hermes-books.yaml"
        path.write_text(
            "metadata_enrichment:\n"
            "  mode: \"aggressive\"\n"
            "  auto_apply_min_confidence: 0.91\n"
            "  require_evidence_url: false\n"
            "  write_cover: false\n"
            "koreader:\n"
            "  metadata_location: \"hashdocsettings\"\n",
            encoding="utf-8",
        )
        cfg = HermesConfig.load(path)

        self.assertEqual(cfg.metadata_enrichment.mode, MetadataEnrichmentMode.AGGRESSIVE)
        self.assertEqual(cfg.metadata_enrichment.auto_apply_min_confidence, 0.91)
        self.assertFalse(cfg.metadata_enrichment.require_evidence_url)
        self.assertFalse(cfg.metadata_enrichment.write_cover)
        self.assertEqual(cfg.koreader.metadata_location, KOReaderMetadataLocation.HASHDOCSETTINGS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.hermes_books.test_models_config`

Expected: import/name failure for new config types or missing `metadata_enrichment`.

- [ ] **Step 3: Implement config dataclasses**

Add enums/configs:

```python
class MetadataEnrichmentMode(str, Enum):
    OFF = "off"
    REPORT_ONLY = "report-only"
    AGGRESSIVE = "aggressive"

class KOReaderMetadataLocation(str, Enum):
    BOOK_FOLDER = "book_folder"
    DOCSETTINGS = "docsettings"
    HASHDOCSETTINGS = "hashdocsettings"
```

Add dataclasses with defaults from the spec and parse them in `HermesConfig.load()`.

- [ ] **Step 4: Update example YAML**

Add `metadata_enrichment` and `koreader` sections matching the spec.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
python -m unittest tests.hermes_books.test_models_config
```

Expected: OK.

Commit:

```powershell
git add scripts/hermes_books/config.py config/hermes-books.example.yaml tests/hermes_books/test_models_config.py
git commit -m "feat: add metadata enrichment config"
```

### Task 2: Metadata Models and Decision Engine

**Files:**
- Create: `scripts/hermes_books/metadata.py`
- Test: `tests/hermes_books/test_metadata.py`

- [ ] **Step 1: Write failing tests for decision filtering**

Create tests that verify high-confidence URL-backed fields apply, low-confidence fields report only, and missing URL fields report only when URL is required:

```python
def test_enricher_applies_only_confident_evidence_backed_decisions(self):
    config = MetadataEnrichmentConfig(auto_apply_min_confidence=0.86, require_evidence_url=True)
    evidence = [
        MetadataEvidence("store-1", "store", "https://example/books/1", {"title": "标准书名"}),
        MetadataEvidence("guess-1", "llm", "", {"publisher": "未知出版社"}),
    ]
    resolution = MetadataResolution(
        decisions=[
            MetadataDecision("title", "旧书名", "标准书名", "apply", 0.93, ["store-1"], "store match"),
            MetadataDecision("publisher", "", "未知出版社", "apply", 0.95, ["guess-1"], "no url"),
            MetadataDecision("isbn", "", "9780000000000", "apply", 0.40, ["store-1"], "low confidence"),
        ]
    )

    report = MetadataEnricher(config).decide(evidence, resolution)

    self.assertEqual([d.field for d in report.applied_decisions], ["title"])
    self.assertEqual({d.field for d in report.reported_decisions}, {"publisher", "isbn"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.hermes_books.test_metadata`

Expected: import failure for `scripts.hermes_books.metadata`.

- [ ] **Step 3: Implement dataclasses and `MetadataEnricher.decide()`**

Implement `MetadataEvidence`, `MetadataDecision`, `MetadataResolution`, `MetadataReport`, `MetadataProvider`, `MetadataReasoner`, and `MetadataEnricher.decide()`.

Decision behavior:

- `mode == off`: no applied decisions.
- `mode == report-only`: no applied decisions.
- `action == block`: goes to conflicts.
- `confidence < auto_apply_min_confidence`: report only.
- missing evidence URL when required: report only.
- otherwise apply.

- [ ] **Step 4: Add JSON/Markdown report helpers**

Implement `MetadataReport.to_json()` and `write_metadata_reports(report, reports_dir)`.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
python -m unittest tests.hermes_books.test_metadata
```

Expected: OK.

Commit:

```powershell
git add scripts/hermes_books/metadata.py tests/hermes_books/test_metadata.py
git commit -m "feat: add metadata enrichment decisions"
```

### Task 3: OPF Metadata and Cover Writer

**Files:**
- Create: `scripts/hermes_books/opf_metadata.py`
- Test: `tests/hermes_books/test_opf_metadata.py`

- [ ] **Step 1: Write failing tests for OPF writes**

Use `make_epub()` and assert:

- `dc:title` changes to enriched title.
- original OPF identifier remains unchanged.
- ISBN is added as an extra identifier.
- subjects and description are added.
- cover write preserves existing cover and creates `images/hermes-metadata-cover.jpg` or a unique suffix.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.hermes_books.test_opf_metadata`

Expected: import failure for `scripts.hermes_books.opf_metadata`.

- [ ] **Step 3: Implement `apply_metadata_to_epub()`**

Signature:

```python
def apply_metadata_to_epub(
    epub_path: Path,
    output_path: Path,
    report: MetadataReport,
    cover_bytes: bytes | None = None,
    cover_media_type: str = "image/jpeg",
) -> Path:
```

Implementation rules:

- Copy all zip entries.
- Parse `META-INF/container.xml` to find OPF.
- Preserve primary `dc:identifier`.
- Replace/add title, creators, publisher, description, subjects.
- Add `meta` entries for `original_title`, `series`, `volume`, `illustrators`, `translators`, `imprint`, `published_date`.
- Add ISBN as extra `dc:identifier` with `opf:scheme="ISBN"` when namespace allows.
- If `cover_bytes` is present, add unique cover href and manifest item with `properties="cover-image"` plus EPUB2 cover meta.

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
python -m unittest tests.hermes_books.test_opf_metadata
```

Expected: OK.

Commit:

```powershell
git add scripts/hermes_books/opf_metadata.py tests/hermes_books/test_opf_metadata.py
git commit -m "feat: write enriched EPUB metadata"
```

### Task 4: Intake Integration and Reports

**Files:**
- Modify: `scripts/hermes_books/intake.py`
- Modify: `scripts/hermes_books/models.py`
- Test: `tests/hermes_books/test_intake.py`

- [ ] **Step 1: Write failing integration tests**

Add `run_intake()` tests that inject static provider/reasoner:

- New book writes `metadata-report.json` and `metadata-report.md`.
- Manifest contains `metadata_report`.
- Published EPUB contains enriched metadata.

Use local `StaticProvider` and `StaticReasoner` classes inside the test.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.hermes_books.test_intake.IntakeTests.test_aggressive_metadata_enrichment_writes_reports_and_epub`

Expected: `run_intake()` does not accept metadata provider/reasoner or missing reports.

- [ ] **Step 3: Extend manifest model**

Add `metadata_report: dict[str, Any] = field(default_factory=dict)` to `BookManifest`.

- [ ] **Step 4: Integrate metadata enrichment**

Add optional parameters to `run_intake()`:

```python
metadata_provider: MetadataProvider | None = None
metadata_reasoner: MetadataReasoner | None = None
metadata_cover_fetcher: Callable[[MetadataReport], bytes | None] | None = None
```

Flow:

- After initial `inspection`, build local clues.
- If mode is not `off` and provider/reasoner exist, search/resolve/decide.
- Apply OPF metadata if `write_epub_metadata` and report has applied decisions.
- Re-inspect after write.
- Write metadata reports.
- Attach `metadata_report` to manifest.
- If provider/reasoner absent, write skipped metadata report.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
python -m unittest tests.hermes_books.test_intake tests.hermes_books.test_metadata tests.hermes_books.test_opf_metadata
```

Expected: OK.

Commit:

```powershell
git add scripts/hermes_books/intake.py scripts/hermes_books/models.py tests/hermes_books/test_intake.py
git commit -m "feat: integrate metadata enrichment intake"
```

### Task 5: KOReader Publish Guard

**Files:**
- Modify: `scripts/hermes_books/intake.py`
- Test: `tests/hermes_books/test_intake.py`

- [ ] **Step 1: Write failing guard tests**

Add tests:

- Existing remote book + aggressive metadata + `book_folder` allows `SAFE_METADATA` publish.
- Existing remote book + aggressive metadata + `hashdocsettings` results in pending/block decision and does not overwrite old remote EPUB.

- [ ] **Step 2: Run test to verify it fails**

Run the two new tests directly.

Expected: `hashdocsettings` path currently publishes or lacks reason.

- [ ] **Step 3: Implement guard**

Before publishing:

- If metadata report status is `applied` and `config.koreader.metadata_location == HASHDOCSETTINGS`, force manifest decision to `BLOCKED_RISKY`, write update diff reason `KOReader hashdocsettings cannot preserve progress after EPUB content hash changes`.
- If `canonical_id` or target path changed, force `BLOCKED_RISKY`.
- If metadata re-inspection shows chapter fingerprint/structure/resource drift against pre-metadata inspection, force `BLOCKED_RISKY`.

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
python -m unittest tests.hermes_books.test_intake
```

Expected: OK.

Commit:

```powershell
git add scripts/hermes_books/intake.py tests/hermes_books/test_intake.py
git commit -m "fix: guard metadata updates for koreader"
```

### Task 6: Full Verification and Documentation

**Files:**
- Modify: `README.md`
- Test: full suite

- [ ] **Step 1: Document usage**

Add a short README section explaining:

- aggressive metadata enrichment is provider/reasoner based.
- path/canonical id are preserved.
- `hashdocsettings` blocks live overwrite.
- reports live under `runs/<job-id>/reports/metadata-report.*`.

- [ ] **Step 2: Run full verification**

Run:

```powershell
python -m unittest tests.hermes_books.test_assets tests.hermes_books.test_build_txt tests.hermes_books.test_diff tests.hermes_books.test_inspect tests.hermes_books.test_intake tests.hermes_books.test_metadata tests.hermes_books.test_models_config tests.hermes_books.test_opf_metadata tests.hermes_books.test_publish tests.hermes_books.test_sources
python -m compileall scripts\hermes_books tests\hermes_books
python -m scripts.hermes_books.intake --help
git diff --check HEAD
```

Expected: all commands exit 0.

- [ ] **Step 3: Commit docs**

```powershell
git add README.md
git commit -m "docs: document aggressive metadata enrichment"
```

- [ ] **Step 4: Request review**

Ask a reviewer to inspect `git diff main..HEAD`, focusing on metadata write safety, KOReader guard, and tests.
