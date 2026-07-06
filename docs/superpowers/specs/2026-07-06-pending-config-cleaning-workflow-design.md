# Pending, Config, and Cleaning Workflow Design

## Goal

Extend Hermes intake from a one-shot publish pipeline into an operator-friendly workflow:

- list and resolve pending WebDAV candidates created by prior runs;
- make currently exposed configuration either real or explicitly reserved;
- make failure reports consistent;
- add a report-only LLM text-cleaning planning layer with cost controls aligned with the ai-workstation routing idea.

The live metadata search/reasoning provider remains intentionally offline in this change. Provider and reasoner injection points stay in place, but no internet search tool is activated by default.

## Non-Goals

- No UMD/JAR handling.
- No direct body rewriting.
- No automatic KOReader sidecar migration.
- No production web search metadata provider.
- No model API calls from Hermes by default.

## Pending Management

Hermes already writes risky candidates to:

```text
/books/.pending/<slug>/<timestamp>-<hash-prefix>-<random>/
  candidate.epub
  candidate.hermes.json
  risk-report.md
```

The new operator flow is local-report driven. It reads `runs/*/reports/publish-report.json`, because every intake run already records the remote pending directory and candidate hash.

Commands:

```powershell
python -m scripts.hermes_books.pending list --runs-root runs
python -m scripts.hermes_books.pending show --report runs/<job-id>/reports/publish-report.json --webdav-root D:\KoreaderDav
python -m scripts.hermes_books.pending approve --report runs/<job-id>/reports/publish-report.json --webdav-root D:\KoreaderDav --confirm <candidate_hash>
python -m scripts.hermes_books.pending reject --report runs/<job-id>/reports/publish-report.json --webdav-root D:\KoreaderDav --confirm <candidate_hash>
```

Approval derives the live target from the pending path:

```text
/books/.pending/<slug>/<pending-id>/candidate.epub
-> /books/<slug>.epub
-> /books/<slug>.hermes.json
```

If a live book exists, approval writes a backup first:

```text
/books/.backups/<slug>/<timestamp>/
  old.epub
  old.hermes.json
```

Writes and deletes use the existing WebDAV conditional APIs where ETags are available. The `--confirm` hash is mandatory so approval cannot be triggered by a stale or wrong report by accident.

## Config Reality

Low-risk config keys become functional:

- `pipeline.language`: passed into TXT-to-EPUB draft generation, including OPF language and chapter HTML language.
- `metadata_enrichment.allow_single_source_fields`: when false, an automatic write needs evidence from at least two distinct sources.
- `metadata_enrichment.block_on_conflicting_identity`: when false, identity conflicts are reported instead of blocking publication.
- `koreader.hashdocsettings_policy`: currently only accepts `block`; any other value fails config load.

Reserved keys remain documented as reserved, not silently implied:

- `pipeline.keep_runs`;
- `pipeline.output_profile`;
- `metadata_enrichment.preserve_target_path`;
- `metadata_enrichment.preserve_canonical_id`.

## Report Consistency

When intake fails before EPUB inspection, the run should still contain:

- `quality-report.md`;
- `asset-report.json`;
- `metadata-report.json`;
- `metadata-report.md`;
- `epubcheck.json`;
- `manifest.json`;
- `publish-report.json`.

The metadata report status is `skipped` with the failure reason.

## Cleaning Report-Only Layer

The new cleaning stage is a reporting stage. It never changes EPUB bytes.

Outputs:

```text
runs/<job-id>/reports/cleaning-report.json
runs/<job-id>/reports/cleaning-report.md
```

Default behavior:

- estimate total text chars from EPUB inspection;
- cap model input using `text_cleaning.max_input_chars`;
- estimate token count and budget;
- write `planned` status if no analyzer is configured;
- write `reported` status if an injected analyzer returns findings;
- write `skipped` status when disabled.

Finding categories are deliberately conservative:

- `site_boilerplate`;
- `advertisement`;
- `chapter_boundary`;
- `missing_chapter`;
- `paragraph_anomaly`;
- `illustration_marker`.

Paragraph anomaly reporting must not assume short paragraphs are wrong. Light novels and web novels frequently use one-line dialogue, scene beats, and dramatic pauses. Findings need reason, location, confidence, and recommended action; body mutation remains outside this change.

## Cost Plan

Hermes should fit the ai-workstation route style:

- rules and EPUB inspection are free and run first;
- MiniMax/M3-class or other local/light route handles cheap classification and extraction;
- DeepSeek long-context route is reserved for manual long-structure analysis;
- GPT-5.5-class review is reserved for high-value final review after explicit operator approval.

The first implementation stores this as a reportable budget plan. It does not call any model. The budget fields are explicit so later MCP/model adapters can enforce hard caps before sending text.

