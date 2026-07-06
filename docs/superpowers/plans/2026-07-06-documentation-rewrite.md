# Hermes Documentation Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite all project documentation around the current Hermes book workflow and mark archived material as historical reference.

**Architecture:** Use code and tests as the source of truth. Rewrite current docs as an executable manual, and archived docs as cleaned historical notes with explicit replacement status.

**Tech Stack:** Markdown, PowerShell, ripgrep, Python unittest/compileall for sanity checks where docs reference runnable modules.

---

### Task 1: Current Documentation Set

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/pipeline.md`
- Modify: `docs/mcp-specs.md`
- Modify: `docs/kindle-setup.md`
- Modify: `docs/daily-reading-rhythm.md`
- Modify: `docs/buying-guide.md`
- Modify: `docs/apple-compatibility.md`

- [ ] Replace outdated claims about Calibre-first automation, completed MCP servers, fixed model routing and old script-only flow.
- [ ] Make `scripts.hermes_books.intake` the documented current entry point.
- [ ] Describe config, reports, metadata enrichment and WebDAV publish decisions using current names from code.
- [ ] Keep personal context in the experience documents, but remove unsupported “already automatic” claims.
- [ ] Use consistent terms: Hermes intake, provider/reasoner, metadata report, update diff, pending candidate, KOReader metadata location.

### Task 2: Archived Documentation Set

**Files:**
- Modify: `archived/ai-integration-blueprint.md`
- Modify: `archived/calibre-automation.md`
- Modify: `archived/format-cheatsheet.md`
- Modify: `archived/guide.md`
- Modify: `archived/local-first-architecture.md`
- Modify: `archived/pipeline-quality.md`

- [ ] Add an archive note to every file explaining that it is historical.
- [ ] Rewrite each file as a concise historical memo.
- [ ] Preserve still-useful ideas such as CSS rules, format handling notes and KOReader settings.
- [ ] Mark superseded parts such as Calibre-first publishing, AZW3-first conversion, fixed model cost tables and planned MCP counts.

### Task 3: Consistency Checks

**Files:**
- All modified Markdown files.

- [ ] Run `rg -n "GLM|DeepSeek|MVP|已部署|规划中|TODO|AZW3|Send to Kindle|Whispersync|calibremcp" README.md docs archived` and inspect every hit.
- [ ] Run `rg -n "scripts/metadata|scripts/txt2epub/pipeline.py|python scripts/" README.md docs archived` to catch stale command examples.
- [ ] Run `python -m unittest tests.hermes_books.test_intake tests.hermes_books.test_metadata tests.hermes_books.test_opf_metadata`.
- [ ] Run `git diff --check HEAD`.
- [ ] Commit with `docs: rewrite Hermes workflow documentation`.

## Self-Review

- Spec coverage: all files in the approved scope have a task.
- Placeholder scan: no TODO/TBD placeholders.
- Scope: pure documentation rewrite; no runtime code changes planned.
