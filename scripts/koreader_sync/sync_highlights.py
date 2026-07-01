#!/usr/bin/env python3
"""
KOReader highlight synchronisation tool.

Parses KOReader JSON highlight files and converts them into structured
formats suitable for Obsidian, general-purpose JSON pipelines, or
plain-text reading.

Usage:
    python sync_highlights.py --source /path/to/highlights.json
    python sync_highlights.py --source /path/to/book_sdr/ --output markdown
    python sync_highlights.py --source webdav://user:pass@host/koreader/highlights/
    python sync_highlights.py --source /path/to/highlights.json --output markdown --output-dir ./notes/
    python sync_highlights.py --source /path/to/highlights.json --watch 30
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Standard KOReader metadata filenames inside an SDR directory
METADATA_FILENAMES = (
    "metadata.lua",
    "metadata.json",
    "settings.reader.lua",
)

# Filename pattern: Author - Title_sdr  (common KOReader SDR naming)
_SDR_DIR_RE = re.compile(
    r"^(?P<author>.+?)\s*[-–—]\s*(?P<title>.+?)(?:_sdr)?$",
    re.IGNORECASE,
)

USER_AGENT = "koreader-sync/1.0 (highlight-tool)"


# ---------------------------------------------------------------------------
# WebDAV helpers
# ---------------------------------------------------------------------------

def _parse_webdav_url(url: str) -> Tuple[str, str, str, str]:
    """Parse a ``webdav://user:pass@host/path`` URL into its components.

    Returns ``(base_url, user, password, directory_path)``.
    """
    # webdav://user:pass@host:port/path  -- strip scheme
    rest = url[len("webdav://"):]
    # Split auth from host+path
    if "@" in rest:
        auth, hostpath = rest.split("@", 1)
        if ":" in auth:
            user, password = auth.split(":", 1)
        else:
            user, password = auth, ""
    else:
        user, password = "", ""
        hostpath = rest

    base = f"http://{hostpath}"
    directory_path = "/"
    # Extract path portion after the first /
    parts = hostpath.split("/", 1)
    if len(parts) == 2:
        directory_path = "/" + parts[1].rstrip("/") + "/"

    return base, user, password, directory_path


def _webdav_list(base: str, user: str, password: str, path: str) -> List[str]:
    """PROPFIND *path* on the WebDAV server and return a list of hrefs."""
    import xml.etree.ElementTree as ET

    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<D:propfind xmlns:D="DAV:"><D:prop><D:displayname/></D:prop></D:propfind>'
    )
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=body.encode("utf-8"),
        method="PROPFIND",
        headers={"User-Agent": USER_AGENT, "Depth": "1"},
    )
    if user:
        import base64 as _b64

        creds = _b64.b64encode(f"{user}:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        sys.stderr.write(
            f"[sync] WebDAV PROPFIND failed (HTTP {exc.code}) for {path}\n"
        )
        return []
    except (urllib.error.URLError, OSError) as exc:
        sys.stderr.write(f"[sync] WebDAV connection error: {exc}\n")
        return []

    root = ET.fromstring(raw)
    ns = {"D": "DAV:"}
    hrefs: List[str] = []
    for resp_elem in root.findall("D:response", ns):
        href_elem = resp_elem.find("D:href", ns)
        if href_elem is not None and href_elem.text:
            hrefs.append(href_elem.text)
    return hrefs


def _webdav_fetch(base: str, user: str, password: str, path: str) -> Optional[bytes]:
    """GET a single file from WebDAV. Returns the raw bytes or *None*."""
    req = urllib.request.Request(
        base.rstrip("/") + path,
        headers={"User-Agent": USER_AGENT},
    )
    if user:
        import base64 as _b64

        creds = _b64.b64encode(f"{user}:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception as exc:
        sys.stderr.write(
            f"[sync] Failed to fetch WebDAV path {path}: {exc}\n"
        )
        return None


def _is_webdav(source: str) -> bool:
    return source.startswith("webdav://")


# ---------------------------------------------------------------------------
# KOReader SDR metadata extraction
# ---------------------------------------------------------------------------

def _extract_sdr_metadata(
    sdr_dir: str,
) -> Dict[str, str]:
    """Try to read metadata from a KOReader SDR directory.

    Looks for ``metadata.lua`` (simple line-based parsing) or
    ``metadata.json``.
    """
    meta: Dict[str, str] = {}

    for fname in METADATA_FILENAMES:
        path = os.path.join(sdr_dir, fname)
        if not os.path.isfile(path):
            continue

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
        except OSError:
            continue

        if fname.endswith(".lua"):
            # Simple Lua key-value: key = "value" or key = [[value]]
            for match in re.finditer(
                r'''(\w+)\s*=\s*(?:\[\[(.+?)\]\]|"(.*?)"|'(.+?)')''',
                raw,
                re.DOTALL,
            ):
                key = match.group(1)
                val = match.group(2) or match.group(3) or match.group(4) or ""
                if key.lower() in ("title", "authors", "author"):
                    norm_key = "author" if key.lower() in ("author", "authors") else "title"
                    meta.setdefault(norm_key, val.strip())
        elif fname.endswith(".json"):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                for k in ("title", "author", "authors"):
                    if k in data and data[k]:
                        norm = "author" if k in ("author", "authors") else k
                        meta.setdefault(norm, str(data[k]))
    return meta


def _guess_metadata_from_path(source: str) -> Dict[str, str]:
    """Heuristically extract title/author from the source path.

    If the source is a directory named like ``Author - Title_sdr``,
    parse it.
    """
    meta: Dict[str, str] = {}
    if _is_webdav(source):
        # Try to guess from the URL path
        path_part = urllib.parse.urlparse(source.replace("webdav://", "http://")).path
        dirname = os.path.basename(path_part.rstrip("/"))
    else:
        dirname = os.path.basename(source.rstrip(os.sep))
        # If source is a file, use its parent dir name
        if os.path.isfile(source):
            dirname = os.path.basename(os.path.dirname(source))

    match = _SDR_DIR_RE.match(dirname)
    if match:
        meta["author"] = match.group("author").strip()
        meta["title"] = match.group("title").strip()
    return meta


# ---------------------------------------------------------------------------
# Highlight parsing & dedup
# ---------------------------------------------------------------------------

def parse_highlights(raw_json: str) -> List[Dict[str, Any]]:
    """Parse a KOReader highlight JSON string into a list of dicts.

    Expected format: a JSON array where each entry has keys like
    ``text``, ``chapter``, ``datetime`` (or ``timestamp``), ``note``,
    ``page``.
    """
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"[sync] Invalid JSON: {exc}\n")
        return []

    if not isinstance(data, list):
        # Sometimes KOReader wraps highlights in an object keyed by page
        if isinstance(data, dict):
            data = data.get("highlight", data.get("highlights", []))
            if not isinstance(data, list):
                sys.stderr.write(
                    "[sync] Unexpected JSON structure; expected a list.\n"
                )
                return []

    results: List[Dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if not entry.get("text"):
            continue  # skip entries with no highlight text

        ts = entry.get("datetime") or entry.get("timestamp") or ""
        results.append({
            "text": str(entry["text"]),
            "chapter": str(entry.get("chapter", "")),
            "timestamp": str(ts),
            "note": str(entry.get("note", "")) if entry.get("note") else "",
            "page": entry.get("page"),
        })
    return results


def deduplicate(highlights: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove highlight entries with identical ``text`` and ``chapter``."""
    seen: set = set()
    unique: List[Dict[str, Any]] = []
    for h in highlights:
        key = hashlib.sha256(
            f"{h['text']}|{h['chapter']}".encode("utf-8")
        ).hexdigest()
        if key not in seen:
            seen.add(key)
            unique.append(h)
    return unique


def group_by_chapter(
    highlights: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Group highlights by their ``chapter`` field.

    Highlights without a chapter go into a key ``(unlabelled)``.
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for h in highlights:
        ch = h["chapter"].strip() or "(unlabelled)"
        groups.setdefault(ch, []).append(h)
    return groups


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def _make_yaml_frontmatter(
    meta: Dict[str, str], highlight_count: int
) -> str:
    """Build Obsidian-compatible YAML frontmatter string."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "---",
        f'title: "{meta.get("title", "Untitled")}"',
        f"author: {meta.get('author', 'Unknown')}",
        f"date: {now}",
        f"highlights: {highlight_count}",
    ]
    if meta.get("book_filename"):
        lines.append(f"source: {meta['book_filename']}")
    lines.append("tags: [kindle, highlights, koreader]")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def format_markdown(
    highlights: List[Dict[str, Any]],
    meta: Dict[str, str],
) -> str:
    """Render highlights as Obsidian-compatible markdown."""
    groups = group_by_chapter(highlights)
    parts = [_make_yaml_frontmatter(meta, len(highlights))]

    title = meta.get("title", "Untitled")
    parts.append(f"# {title} — Highlights")
    parts.append("")

    for chapter, items in groups.items():
        parts.append(f"## {chapter}")
        parts.append("")
        for h in items:
            parts.append(f"> {h['text']}")
            if h.get("note"):
                parts.append(f"  — *Note:* {h['note']}")
            if h.get("page"):
                parts.append(f"  — page {h['page']}")
            parts.append("")
    return "\n".join(parts)


def format_json_output(
    highlights: List[Dict[str, Any]],
    meta: Dict[str, str],
) -> str:
    """Render highlights as a clean JSON document."""
    groups = group_by_chapter(highlights)
    output: Dict[str, Any] = {
        "meta": {
            "title": meta.get("title", "Untitled"),
            "author": meta.get("author", "Unknown"),
        },
        "total_highlights": len(highlights),
        "chapters": {},
    }
    for chapter, items in groups.items():
        output["chapters"][chapter] = items
    return json.dumps(output, ensure_ascii=False, indent=2)


def format_text(
    highlights: List[Dict[str, Any]],
    meta: Dict[str, str],
) -> str:
    """Render highlights as plain text with chapter grouping."""
    groups = group_by_chapter(highlights)
    lines: List[str] = []
    title = meta.get("title", "Untitled")
    author = meta.get("author", "Unknown")
    lines.append(f"{title}")
    if author:
        lines.append(f"by {author}")
    lines.append(f"{len(highlights)} highlights")
    lines.append("=" * 60)
    lines.append("")

    for chapter, items in groups.items():
        lines.append(f"--- {chapter} ---")
        lines.append("")
        for h in items:
            lines.append(f"  * {h['text']}")
            if h.get("note"):
                lines.append(f"    [Note: {h['note']}]")
            if h.get("page"):
                lines.append(f"    [Page: {h['page']}]")
            lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Source loading
# ---------------------------------------------------------------------------

def load_highlights(source: str) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """Load highlights from *source* (local path or webdav URL).

    Returns ``(highlights, metadata_dict)``.
    """
    meta: Dict[str, str] = _guess_metadata_from_path(source)

    if _is_webdav(source):
        base, user, password, dirpath = _parse_webdav_url(source)
        # List files, find JSON highlight files
        hrefs = _webdav_list(base, user, password, dirpath)
        all_highlights: List[Dict[str, Any]] = []
        for href in hrefs:
            if not href.lower().endswith(".json"):
                continue
            raw = _webdav_fetch(base, user, password, href)
            if raw is None:
                continue
            all_highlights.extend(parse_highlights(raw.decode("utf-8", errors="replace")))

        # Try to read metadata from the remote SDR directory too
        for meta_file in METADATA_FILENAMES:
            raw = _webdav_fetch(base, user, password, dirpath + meta_file)
            if raw is not None:
                meta.update(_extract_remote_metadata(raw, meta_file))
        return deduplicate(all_highlights), meta

    # --- Local path ---
    if os.path.isdir(source):
        # SDR directory: read the primary JSON highlight file(s)
        all_highlights: List[Dict[str, Any]] = []
        sdr_meta = _extract_sdr_metadata(source)
        meta.update(sdr_meta)

        for entry in os.listdir(source):
            if not entry.lower().endswith(".json"):
                continue
            fpath = os.path.join(source, entry)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                    all_highlights.extend(parse_highlights(fh.read()))
            except OSError as exc:
                sys.stderr.write(f"[sync] Cannot read {fpath}: {exc}\n")

        # Also check parent dir for SDR naming
        parent_meta = _guess_metadata_from_path(source)
        for k, v in parent_meta.items():
            meta.setdefault(k, v)

        return deduplicate(all_highlights), meta

    # Single file
    try:
        with open(source, "r", encoding="utf-8", errors="replace") as fh:
            highlights = parse_highlights(fh.read())
    except OSError as exc:
        sys.stderr.write(f"[sync] Cannot read {source}: {exc}\n")
        return [], meta

    # Try the parent SDR directory for metadata
    parent = os.path.dirname(source)
    if os.path.isdir(parent):
        sdr_meta = _extract_sdr_metadata(parent)
        meta.update(sdr_meta)
    parent_meta = _guess_metadata_from_path(source)
    for k, v in parent_meta.items():
        meta.setdefault(k, v)

    return deduplicate(highlights), meta


def _extract_remote_metadata(raw: bytes, filename: str) -> Dict[str, str]:
    """Extract metadata from a remotely-fetched metadata file's bytes."""
    meta: Dict[str, str] = {}
    text = raw.decode("utf-8", errors="replace")

    if filename.endswith(".lua"):
        for match in re.finditer(
            r'''(\w+)\s*=\s*(?:\[\[(.+?)\]\]|"(.*?)"|'(.+?)')''',
            text,
            re.DOTALL,
        ):
            key = match.group(1)
            val = match.group(2) or match.group(3) or match.group(4) or ""
            if key.lower() in ("title", "authors", "author"):
                norm_key = "author" if key.lower() in ("author", "authors") else "title"
                meta.setdefault(norm_key, val.strip())
    elif filename.endswith(".json"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return meta
        if isinstance(data, dict):
            for k in ("title", "author", "authors"):
                if k in data and data[k]:
                    norm = "author" if k in ("author", "authors") else k
                    meta.setdefault(norm, str(data[k]))
    return meta


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def sync_highlights(
    source: str,
    output_format: str = "json",
    output_dir: Optional[str] = None,
) -> int:
    """Load, process, and output highlights.

    Returns 0 on success, non-zero on failure.
    """
    highlights, meta = load_highlights(source)

    if not highlights:
        sys.stderr.write("[sync] No highlights found.\n")
        return 1

    meta.setdefault("book_filename", os.path.basename(source.rstrip("/\\")))

    # Render
    formatters: Dict[str, Callable[[List[Dict[str, Any]], Dict[str, str]], str]] = {
        "json": format_json_output,
        "markdown": format_markdown,
        "text": format_text,
    }
    formatter = formatters.get(output_format, format_json_output)
    output_text = formatter(highlights, meta)

    # Extension mapping
    ext_map = {"json": ".json", "markdown": ".md", "text": ".txt"}
    ext = ext_map.get(output_format, ".json")

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        safe_title = re.sub(
            r"[<>:\"/\\|?*']", "_",
            meta.get("title", "highlights"),
        )
        out_path = os.path.join(output_dir, f"{safe_title}{ext}")
        try:
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(output_text)
            sys.stderr.write(f"[sync] Written: {out_path}\n")
        except OSError as exc:
            sys.stderr.write(f"[sync] Cannot write {out_path}: {exc}\n")
            return 1
    else:
        sys.stdout.write(output_text)

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="KOReader highlight synchronisation tool.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sync_highlights.py --source /path/to/highlights.json
  python sync_highlights.py --source /path/to/book_sdr/ --output markdown
  python sync_highlights.py --source webdav://user:pass@host/koreader/highlights/
  python sync_highlights.py --source /path/to/highlights.json --output markdown --output-dir ./notes/
  python sync_highlights.py --source /path/to/highlights.json --watch 30
        """.strip(),
    )
    parser.add_argument(
        "--source", required=True,
        help=(
            "Path to a KOReader highlight JSON file, an SDR directory, or a "
            "webdav:// URL pointing to a remote highlights directory."
        ),
    )
    parser.add_argument(
        "--output", choices=["json", "markdown", "text"], default="json",
        help="Output format. 'markdown' includes Obsidian YAML frontmatter.",
    )
    parser.add_argument(
        "--output-dir", metavar="DIR",
        help=(
            "Directory to write the output file into. "
            "If omitted, output is printed to stdout."
        ),
    )
    parser.add_argument(
        "--watch", type=int, default=0, metavar="SECONDS",
        help=(
            "Poll the source every N seconds for new highlights. "
            "Useful for continuous sync."
        ),
    )

    args = parser.parse_args(argv)

    if args.watch > 0:
        sys.stderr.write(
            f"[sync] Watching {args.source} every {args.watch}s. "
            "Press Ctrl+C to stop.\n"
        )
        try:
            while True:
                exit_code = sync_highlights(
                    args.source,
                    output_format=args.output,
                    output_dir=args.output_dir,
                )
                if exit_code != 0:
                    sys.stderr.write(
                        f"[sync] Sync returned exit code {exit_code}. "
                        "Will retry on next poll.\n"
                    )
                time.sleep(args.watch)
        except KeyboardInterrupt:
            sys.stderr.write("\n[sync] Watch stopped.\n")
            sys.exit(0)
    else:
        sys.exit(sync_highlights(
            args.source,
            output_format=args.output,
            output_dir=args.output_dir,
        ))


if __name__ == "__main__":
    main()
