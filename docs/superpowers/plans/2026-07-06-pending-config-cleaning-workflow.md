# Pending Config Cleaning Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pending-candidate approval/rejection, make exposed config truthful, produce consistent failure reports, and add a report-only LLM cleaning cost plan.

**Architecture:** Keep risky write logic in focused modules. `pending.py` operates on existing `publish-report.json` plus the existing `WebDavClient` protocol. `cleaning.py` produces deterministic reports and accepts an injected analyzer, while intake only orchestrates and writes artifacts.

**Tech Stack:** Python 3 standard library, `ebooklib`, current Hermes modules, `unittest`, existing local WebDAV adapter.

---

### Task 1: Pending Manager

**Files:**
- Create: `scripts/hermes_books/pending.py`
- Create: `tests/hermes_books/test_pending.py`
- Modify: `README.md`
- Modify: `docs/pipeline.md`

- [ ] **Step 1: Write failing tests**

Create tests that build a pending directory through `WebDavPublisher`, write a matching `publish-report.json`, then verify:

```python
pending = list_pending_reports(runs_root)
assert pending[0].candidate_hash == report["candidate_hash"]
approval = approve_pending_report(report_path, client, confirm_hash=report["candidate_hash"])
assert approval["status"] == "approved"
assert live_epub.read_bytes() == b"candidate"
```

Also test rejection removes `candidate.epub`, `candidate.hermes.json`, and `risk-report.md`.

- [ ] **Step 2: Verify red**

Run:

```powershell
python -m unittest tests.hermes_books.test_pending
```

Expected: import failure for `scripts.hermes_books.pending`.

- [ ] **Step 3: Implement pending module**

Add:

- `PendingReport` dataclass;
- `list_pending_reports(runs_root)`;
- `load_pending_report(report_path)`;
- `approve_pending_report(report_path, client, confirm_hash, timestamp=None)`;
- `reject_pending_report(report_path, client, confirm_hash)`;
- CLI commands `list`, `show`, `approve`, `reject`.

Approval writes backups before live overwrite and uses conditional writes when live ETags exist.

- [ ] **Step 4: Verify green**

Run:

```powershell
python -m unittest tests.hermes_books.test_pending
python -m scripts.hermes_books.pending --help
```

Expected: all pending tests pass and CLI help exits zero.

### Task 2: Config Behavior

**Files:**
- Modify: `scripts/hermes_books/config.py`
- Modify: `scripts/hermes_books/build.py`
- Modify: `scripts/hermes_books/intake.py`
- Modify: `scripts/hermes_books/metadata.py`
- Modify: `tests/hermes_books/test_build_txt.py`
- Modify: `tests/hermes_books/test_models_config.py`
- Modify: `tests/hermes_books/test_metadata.py`

- [ ] **Step 1: Write failing tests**

Add tests for:

```python
draft = build_draft_from_txt(job, raw_path, draft_dir, language="ja")
assert book.get_metadata("DC", "language")[0][0] == "ja"
```

```python
cfg = HermesConfig.load(path_with_hashdocsettings_policy_keep)
```

Expected: raises `ValueError` unless value is `block`.

```python
config = MetadataEnrichmentConfig(allow_single_source_fields=False)
report = MetadataEnricher(config).decide(single_source_evidence, resolution)
assert report.status == "reported"
```

```python
config = MetadataEnrichmentConfig(block_on_conflicting_identity=False)
report = MetadataEnricher(config).decide(evidence, identity_block_resolution)
assert report.status == "reported"
```

- [ ] **Step 2: Verify red**

Run:

```powershell
python -m unittest tests.hermes_books.test_build_txt tests.hermes_books.test_models_config tests.hermes_books.test_metadata
```

Expected: failures for missing language parameter and ignored config keys.

- [ ] **Step 3: Implement config behavior**

Update TXT build language, config validation, and metadata decision gates.

- [ ] **Step 4: Verify green**

Run the same unittest command. Expected: all selected tests pass.

### Task 3: Consistent Reports and Cleaning Report

**Files:**
- Create: `scripts/hermes_books/cleaning.py`
- Create: `tests/hermes_books/test_cleaning.py`
- Modify: `scripts/hermes_books/config.py`
- Modify: `scripts/hermes_books/intake.py`
- Modify: `tests/hermes_books/test_intake.py`
- Modify: `config/hermes-books.example.yaml`

- [ ] **Step 1: Write failing tests**

Add tests that assert:

```python
assert (result.reports_dir / "metadata-report.json").exists()
assert metadata["status"] == "skipped"
```

for pre-inspection failures.

Add cleaning tests:

```python
report = CleaningPlanner(TextCleaningConfig()).plan(inspection)
assert report.status == "planned"
assert report.cost_plan["selected_route"] == "rules-first-report-only"
```

And an intake integration test asserting `cleaning-report.json` exists.

- [ ] **Step 2: Verify red**

Run:

```powershell
python -m unittest tests.hermes_books.test_cleaning tests.hermes_books.test_intake
```

Expected: import failure for cleaning and missing metadata failure report assertion.

- [ ] **Step 3: Implement cleaning and report consistency**

Add `TextCleaningConfig`, `CleaningFinding`, `CleaningReport`, `CleaningPlanner`, `write_cleaning_reports`, and intake orchestration. Pre-inspection failures write skipped cleaning and metadata reports.

- [ ] **Step 4: Verify green**

Run the same unittest command. Expected: all selected tests pass.

### Task 4: Documentation and Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/pipeline.md`
- Modify: `docs/architecture.md`
- Modify: `docs/mcp-specs.md`
- Modify: `config/hermes-books.example.yaml`

- [ ] **Step 1: Document operator commands**

Update docs with pending approval/rejection commands and explain that no production metadata web provider is enabled.

- [ ] **Step 2: Document cost plan**

Document report-only cleaning, model routes, and hard budget caps.

- [ ] **Step 3: Full verification**

Run:

```powershell
python -m unittest tests.hermes_books.test_assets tests.hermes_books.test_build_txt tests.hermes_books.test_cleaning tests.hermes_books.test_diff tests.hermes_books.test_inspect tests.hermes_books.test_intake tests.hermes_books.test_metadata tests.hermes_books.test_models_config tests.hermes_books.test_opf_metadata tests.hermes_books.test_pending tests.hermes_books.test_publish tests.hermes_books.test_sources
python -m compileall scripts\hermes_books tests\hermes_books
python -m scripts.hermes_books.intake --help
python -m scripts.hermes_books.pending --help
git diff --check HEAD
```

Expected: all commands exit zero.

