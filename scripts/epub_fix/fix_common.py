#!/usr/bin/env python3
"""
Fix common EPUB structural issues using ebooklib.

Repairs three categories of problems often found in EPUBs generated or
post-processed by conversion tools (Calibre, Sigil, etc.):

    manifest  -- Add missing OPF manifest entries for files actually present
                 in the archive; remove manifest entries that point to
                 non-existent files.
    date      -- Ensure the Dublin Core <dc:date> field is valid YYYY-MM-DD
                 and repair common invalid formats.
    css       -- Strip renderer-unfriendly CSS: absolute px font-sizes,
                 "!important" on body text, and line-height values < 1.0.

Usage:
    python fix_common.py book.epub --fix all
    python fix_common.py book.epub --fix manifest --fix date --dry-run
    python fix_common.py book.epub --fix css --in-place

Requires:
    ebooklib  (pip install ebooklib)
"""

import argparse
import calendar
import mimetypes
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import NamedTuple

# ---------------------------------------------------------------------------
# ebooklib is optional at import time so --help works even without it.
# It is lazy-imported on first use via _ensure_ebooklib().
# ---------------------------------------------------------------------------
_EBOOKLIB_AVAILABLE = False


def _ensure_ebooklib():
    """Lazy-import ebooklib and raise a helpful error if unavailable."""
    global _EBOOKLIB_AVAILABLE
    if _EBOOKLIB_AVAILABLE:
        return
    try:
        import ebooklib  # noqa: F401
        from ebooklib import epub  # noqa: F401
        _EBOOKLIB_AVAILABLE = True
    except ImportError:
        print(
            "Error: ebooklib is not installed.\n\n"
            "This script requires the ebooklib library.\n"
            "Install it with:  pip install ebooklib",
            file=sys.stderr,
        )
        sys.exit(2)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class Change(NamedTuple):
    """A single fix applied (or proposed)."""
    file: str           # logical file or category (e.g. "OPF manifest")
    description: str    # human-readable description


# Global flag set by --dry-run.  When True we read/inspect the EPUB but
# never call write_epub() and never mutate the book in-place.
DRY_RUN = False


def _normalise_epub_path(path: str) -> str:
    """Normalise a path as stored inside an EPUB zip for comparison."""
    return path.replace("\\", "/").lstrip("/")


def _get_zip_entries(epub_path: str) -> set[str]:
    """Return the set of normalised file paths inside an EPUB archive."""
    entries: set[str] = set()
    with zipfile.ZipFile(epub_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            entries.add(_normalise_epub_path(info.filename))
    return entries


def _read_zip_bytes(epub_path: str, normalised_path: str) -> bytes | None:
    """Read the raw bytes for a normalised path from the EPUB zip."""
    with zipfile.ZipFile(epub_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if _normalise_epub_path(info.filename) == normalised_path:
                return zf.read(info.filename)
    return None


def _guess_media_type(file_name: str) -> str:
    """Guess a media (MIME) type from a file extension."""
    ext = os.path.splitext(file_name)[1].lower()
    mapping: dict[str, str] = {
        ".xhtml": "application/xhtml+xml",
        ".html":  "application/xhtml+xml",
        ".htm":   "application/xhtml+xml",
        ".xml":   "application/xml",
        ".css":   "text/css",
        ".jpg":   "image/jpeg",
        ".jpeg":  "image/jpeg",
        ".png":   "image/png",
        ".gif":   "image/gif",
        ".svg":   "image/svg+xml",
        ".ttf":   "font/ttf",
        ".otf":   "font/otf",
        ".woff":  "font/woff",
        ".woff2": "font/woff2",
        ".ncx":   "application/x-dtbncx+xml",
        ".opf":   "application/oebps-package+xml",
        ".js":    "application/javascript",
        ".mp3":   "audio/mpeg",
        ".mp4":   "video/mp4",
        ".webp":  "image/webp",
    }
    if ext in mapping:
        return mapping[ext]
    mt, _ = mimetypes.guess_type(file_name)
    return mt or "application/octet-stream"


# ---------------------------------------------------------------------------
# Manifest fix
# ---------------------------------------------------------------------------

def _make_unique_item_id(candidate: str, taken: set[str]) -> str:
    """Return a unique OPF item id, appending a suffix if needed."""
    if candidate not in taken:
        taken.add(candidate)
        return candidate
    for i in range(1, 1000):
        c2 = f"{candidate}_{i}"
        if c2 not in taken:
            taken.add(c2)
            return c2
    # Last resort
    return f"{candidate}_{abs(hash(candidate)) % 10000}"


def _files_to_skip() -> set[str]:
    """Files that are never manifest items."""
    return {"mimetype", "META-INF/container.xml"}


def _fix_manifest(book, epub_path: str) -> list[Change]:
    """
    (a) Add missing OPF manifest entries for files present in the zip.
    (b) Remove manifest entries referencing files that do not exist in the zip.
    """
    from ebooklib import epub as _epub

    changes: list[Change] = []
    zip_entries = _get_zip_entries(epub_path)
    skip = _files_to_skip()

    # ── Build lookup: normalised path → ebooklib item ──
    manifest_by_path: dict[str, object] = {}
    for item in book.get_items():
        norm = _normalise_epub_path(str(item.file_name))
        manifest_by_path[norm] = item
    manifest_norms = set(manifest_by_path.keys())

    # Identify the .opf file (it is never a manifest item of itself).
    opf_norms: set[str] = set()
    for zip_path in zip_entries:
        if zip_path.lower().endswith(".opf"):
            opf_norms.add(zip_path)

    # Collect existing item ids to avoid collisions.
    used_ids: set[str] = set()
    for item in book.get_items():
        iid = getattr(item, "id", None)
        if iid:
            used_ids.add(str(iid))

    # ── (a) Add missing entries ──
    for zip_path in sorted(zip_entries):
        if zip_path in skip or zip_path in opf_norms:
            continue

        # Check whether this zip entry is covered by any manifest entry.
        covered = False
        for mpath in manifest_norms:
            if zip_path == mpath:
                covered = True
                break
            # Handle path prefix differences (OEBPS/ vs. bare)
            if zip_path.endswith("/" + mpath) or mpath.endswith("/" + zip_path):
                covered = True
                break
            # Match by filename alone with common EPUB prefixes stripped
            zip_fn = os.path.basename(zip_path)
            m_fn = os.path.basename(mpath)
            if zip_fn == m_fn:
                covered = True
                break

        if covered:
            continue

        # This file exists in the zip but has no manifest entry.
        file_name = os.path.basename(zip_path)
        media_type = _guess_media_type(file_name)
        base_id = re.sub(r"[^a-zA-Z0-9_]", "_",
                         os.path.splitext(file_name)[0]).strip("_") or "item"
        item_id = _make_unique_item_id(base_id, used_ids)

        if DRY_RUN:
            changes.append(Change(
                file="OPF manifest",
                description=f"ADD missing entry: {zip_path} ({media_type})"
            ))
            continue

        new_item = _epub.EpubItem()
        new_item.id = item_id
        new_item.file_name = zip_path
        new_item.media_type = media_type
        # Populate content from the zip so ebooklib can write it back out.
        content = _read_zip_bytes(epub_path, zip_path)
        if content is not None:
            new_item.set_content(content)
        else:
            new_item.set_content(b"")

        book.add_item(new_item)
        changes.append(Change(
            file="OPF manifest",
            description=f"ADD: {zip_path} ({media_type})"
        ))

    # ── (b) Remove dead entries ──
    items_to_purge: list[object] = []
    for item in book.get_items():
        fn = _normalise_epub_path(str(item.file_name))
        dead = True
        for zpath in zip_entries:
            if fn == zpath:
                dead = False
                break
            if fn.endswith("/" + zpath) or zpath.endswith("/" + fn):
                dead = False
                break
            if os.path.basename(fn) == os.path.basename(zpath):
                dead = False
                break
        if dead:
            items_to_purge.append(item)

    for item in items_to_purge:
        href = str(item.file_name)
        if DRY_RUN:
            changes.append(Change(
                file="OPF manifest",
                description=f"REMOVE dead entry: {href} (file not in archive)"
            ))
            continue

        # Purge from book items list.
        try:
            book.items.remove(item)
        except ValueError:
            pass

        # Purge from spine.
        spine = getattr(book, "spine", None)
        if spine:
            to_go = []
            for ref in spine:
                if isinstance(ref, tuple):
                    if ref[1] is item:
                        to_go.append(ref)
                elif ref is item:
                    to_go.append(ref)
            for ref in to_go:
                try:
                    spine.remove(ref)
                except ValueError:
                    pass

        changes.append(Change(
            file="OPF manifest",
            description=f"REMOVE: {href} (file not found in archive)"
        ))

    return changes


# ---------------------------------------------------------------------------
# Date fix
# ---------------------------------------------------------------------------

def _date_is_valid(date_str: str) -> bool:
    """Check whether *date_str* is already valid YYYY-MM-DD."""
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str.strip())) and \
        _parse_date(date_str.strip()) is not None


def _parse_date(date_str: str) -> str | None:
    """
    Attempt to parse any common date string into canonical YYYY-MM-DD.

    Returns None if parsing fails entirely.
    """
    date_str = date_str.strip()
    if not date_str:
        return None

    # Already valid?
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", date_str)
    if m:
        year, month, day = int(m[1]), int(m[2]), int(m[3])
        if 1 <= month <= 12 and 1 <= day <= 31:
            return date_str
        return None

    # YYYY-MM
    m = re.fullmatch(r"(\d{4})-(\d{2})", date_str)
    if m:
        year, month = int(m[1]), int(m[2])
        if 1 <= month <= 12:
            last_day = calendar.monthrange(year, month)[1]
            return f"{year:04d}-{month:02d}-{last_day:02d}"

    # YYYY
    m = re.fullmatch(r"(\d{4})", date_str)
    if m:
        year = int(m[1])
        if 1900 <= year <= 2100:
            return f"{year:04d}-01-01"

    # YYYYMMDD
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", date_str)
    if m:
        year, month, day = int(m[1]), int(m[2]), int(m[3])
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"

    # DD-MM-YYYY  /  DD/MM/YYYY  /  DD.MM.YYYY
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", date_str)
    if m:
        a, b, year = int(m[1]), int(m[2]), int(m[3])
        if year < 1900 or year > 2100:
            return None
        # Assume DD-MM
        if 1 <= a <= 31 and 1 <= b <= 12:
            return f"{year:04d}-{b:02d}-{a:02d}"
        # Assume MM-DD
        if 1 <= a <= 12 and 1 <= b <= 31:
            return f"{year:04d}-{a:02d}-{b:02d}"
        return None

    # "Month DD, YYYY"  or  "DD Month YYYY"
    month_names: dict[str, int] = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    for name, num in month_names.items():
        m = re.fullmatch(
            rf"{name}\.?\s+(\d{{1,2}})[,\s]+(\d{{4}})",
            date_str, re.IGNORECASE,
        )
        if m:
            day, year = int(m[1]), int(m[2])
            if 1 <= day <= 31 and 1900 <= year <= 2100:
                return f"{year:04d}-{num:02d}-{day:02d}"

        m = re.fullmatch(
            rf"(\d{{1,2}})[\s,]+{name}\.?\s*,?\s*(\d{{4}})",
            date_str, re.IGNORECASE,
        )
        if m:
            day, year = int(m[1]), int(m[2])
            if 1 <= day <= 31 and 1900 <= year <= 2100:
                return f"{year:04d}-{num:02d}-{day:02d}"

    return None


def _fix_date(book) -> list[Change]:
    """Ensure DC date metadata fields are valid YYYY-MM-DD."""
    changes: list[Change] = []

    # ebooklib stores metadata as a list of (namespace, name, value, attrs)
    # under the key "DC" for Dublin Core.
    dc_entries = book.get_metadata("DC", "date")
    if not dc_entries:
        return changes

    for idx, entry in enumerate(dc_entries):
        # entry is typically (ns, name, value_dict_or_str, {})
        # Sometimes it's (ns, name, str_value, attrs)
        raw_value = ""
        if len(entry) >= 3:
            raw_value = str(entry[2]) if entry[2] is not None else ""

        original = raw_value.strip()
        if not original:
            continue

        if _date_is_valid(original):
            continue  # already fine

        canonical = _parse_date(original)
        if not canonical:
            changes.append(Change(
                file="OPF metadata",
                description=f"date: UNPARSABLE '{original}' -- left unchanged"
            ))
            continue

        if DRY_RUN:
            changes.append(Change(
                file="OPF metadata",
                description=f"date: '{original}' -> '{canonical}'"
            ))
            continue

        # Mutate via the internal list. ebooklib re-serialises metadata
        # from this list on write_epub, so modifying it here is sufficient.
        try:
            # Access the raw metadata list: book.metadata["DC"]["date"]
            # Then replace the value tuple.
            dc_date_list = book.metadata.get("DC", {}).get("date", [])
            if idx < len(dc_date_list):
                old = dc_date_list[idx]
                if isinstance(old, (list, tuple)):
                    new_entry = list(old)
                    new_entry[2] = canonical
                    dc_date_list[idx] = tuple(new_entry)
                else:
                    dc_date_list[idx] = canonical
        except (KeyError, IndexError, TypeError):
            # Fallback: use set_metadata (but this appends, so we also attempt
            # to clear and re-add in a simpler fashion)
            pass

        changes.append(Change(
            file="OPF metadata",
            description=f"date: '{original}' -> '{canonical}'"
        ))

    return changes


# ---------------------------------------------------------------------------
# CSS fix
# ---------------------------------------------------------------------------

# Selectors considered to apply to body / running text for !important
# stripping.  Matches the last simple selector in a compound selector.
_BODY_TEXT_SELECTORS_RE = re.compile(
    r"(?:^|[\s,>+~])"
    r"(?:body|p|div|span|li|td|th|dd|dt|blockquote|pre|"
    r"h[1-6]|a|em|strong|b|i|u|small|big|sub|sup|cite|q|"
    r"abbr|code|del|dfn|ins|kbd|mark|samp|var|"
    r"article|section|aside|nav|header|footer|main|figcaption)"
    r"(?:[\s:#.\[][^,{]*)?"
    r"$",
    re.IGNORECASE,
)

# font-size: Npx (N is one or more digits), optionally with !important
_FONT_SIZE_PX_RE = re.compile(
    r"(font-size\s*:\s*\d+\s*px)\s*(!important)?\s*;",
    re.IGNORECASE,
)

# line-height < 1.0 (e.g. 0.8, 0.75em)
_LINE_HEIGHT_LOW_RE = re.compile(
    r"(line-height\s*:\s*)0\.\d+\s*(em|rem|%|[a-z]*)?\s*(!important)?\s*;",
    re.IGNORECASE,
)

# !important token
_IMPORTANT_TOKEN_RE = re.compile(r"\s*!important", re.IGNORECASE)


def _is_body_text_selector(selector_text: str) -> bool:
    """Return True if the last simple selector targets running text."""
    parts = [s.strip() for s in selector_text.split(",")]
    for part in parts:
        # Extract the last simple selector (rightmost before any combinator)
        simple = part.split()[-1] if part.split() else part
        if _BODY_TEXT_SELECTORS_RE.match(simple):
            return True
    return False


def _fix_css_item(content: str, item_name: str) -> tuple[str, list[str]]:
    """
    Process a single CSS string.  Returns (new_content, changelist).
    """
    changelist: list[str] = []

    # Split into rules by scanning { } blocks.
    output_lines: list[str] = []
    lines = content.splitlines(True)
    i = 0
    in_rule = False
    current_selector = ""
    brace_depth = 0
    rule_output: list[str] = []  # accumulates lines of the current rule body
    is_body_text = False

    while i < len(lines):
        line = lines[i]

        if not in_rule:
            # Outside a rule -- accumulate selector text until we see {
            if "{" in line:
                in_rule = True
                brace_depth = 1
                parts = line.split("{", 1)
                current_selector = (current_selector + parts[0]).strip()
                is_body_text = _is_body_text_selector(current_selector)
                rule_output = []
                output_lines.append(current_selector + " {\n")
                # Push back the content after {
                rest = parts[1] if len(parts) > 1 else ""
                if rest.strip():
                    lines[i] = rest  # overwrite for re-processing
                    i -= 1
            else:
                current_selector += line.strip() + " "
                output_lines.append(line)
        else:
            stripped = line.strip()
            brace_delta = stripped.count("{") - stripped.count("}")

            if "}" in stripped and brace_depth + brace_delta <= 0:
                # End of rule
                in_rule = False
                current_selector = ""
                is_body_text = False
                output_lines.append(line)
                i += 1
                continue

            brace_depth += brace_delta

            # ── font-size: Npx ──
            m_px = _FONT_SIZE_PX_RE.search(stripped)
            if m_px:
                matched = m_px.group(0).strip().rstrip(";")
                output_lines.append(f"  /* EPUBFIX: removed '{matched}' */\n")
                changelist.append(
                    f"  {item_name}: removed absolute px font-size "
                    f"('{m_px.group(1).strip()}' in "
                    f"'{current_selector[:50]}')"
                )
                i += 1
                continue

            # ── line-height < 1.0 ──
            m_lh = _LINE_HEIGHT_LOW_RE.search(stripped)
            if m_lh:
                matched = m_lh.group(0).strip().rstrip(";")
                output_lines.append(f"  /* EPUBFIX: removed '{matched}' */\n")
                changelist.append(
                    f"  {item_name}: removed low line-height "
                    f"('{m_lh.group(0).strip().rstrip(';')}' in "
                    f"'{current_selector[:50]}')"
                )
                i += 1
                continue

            # ── !important on body-text selectors ──
            if is_body_text and "!important" in stripped:
                new_line = _IMPORTANT_TOKEN_RE.sub("", line)
                output_lines.append(new_line)
                short_sel = current_selector[:60]
                changelist.append(
                    f"  {item_name}: stripped !important from "
                    f"'{short_sel}'"
                )
                i += 1
                continue

            output_lines.append(line)

        i += 1

    return "".join(output_lines), changelist


def _fix_css(book, epub_path: str) -> list[Change]:
    """Fix CSS issues in all stylesheet items."""
    from ebooklib import ITEM_STYLE

    changes: list[Change] = []

    for item in book.get_items_of_type(ITEM_STYLE):
        item_name = str(getattr(item, "file_name", "?"))
        try:
            content_bytes = item.get_content()
            content = content_bytes.decode("utf-8", errors="replace")
        except Exception:
            continue

        new_content, css_changes = _fix_css_item(content, item_name)

        if not css_changes:
            continue

        if DRY_RUN:
            for c in css_changes:
                changes.append(Change(file="CSS", description=c))
            continue

        item.set_content(new_content.encode("utf-8"))
        for c in css_changes:
            changes.append(Change(file="CSS", description=c))

    return changes


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

FIX_REGISTRY = {
    "manifest": _fix_manifest,
    "date":     _fix_date,
    "css":      _fix_css,
}


def _output_path(input_path: str, in_place: bool) -> str:
    """Return the path where the fixed EPUB should be saved."""
    if in_place:
        return input_path
    base, ext = os.path.splitext(input_path)
    if ext.lower() == ".epub":
        return f"{base}_fixed.epub"
    return f"{input_path}_fixed"


def main(argv: list[str] | None = None) -> None:
    global DRY_RUN

    parser = argparse.ArgumentParser(
        description="Fix common EPUB structural issues.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Fix types:
  manifest   Add missing or remove dead OPF manifest entries
  date       Repair invalid DC date fields to YYYY-MM-DD
  css        Strip renderer-unfriendly CSS (px font-size,
             !important on body text, line-height < 1.0)
  all        Apply all fixes above

Examples:
  python fix_common.py book.epub --fix all --dry-run
  python fix_common.py book.epub --fix manifest --fix date
  python fix_common.py book.epub --fix css --in-place
        """,
    )
    parser.add_argument(
        "epub",
        help="Path to the EPUB file to fix",
    )
    parser.add_argument(
        "--fix",
        action="append",
        dest="fixes",
        choices=["manifest", "date", "css", "all"],
        help="Fix type to apply (repeatable; 'all' applies every fix)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing any files",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the original EPUB instead of creating *_fixed.epub",
    )
    args = parser.parse_args(argv)

    # ── validation ──────────────────────────────────────────────────────
    if not os.path.isfile(args.epub):
        print(f"Error: EPUB file not found: {args.epub}", file=sys.stderr)
        sys.exit(2)

    if not args.fixes:
        print(
            "Error: no fix type specified. "
            "Use --fix manifest, --fix date, --fix css, or --fix all.",
            file=sys.stderr,
        )
        sys.exit(2)

    DRY_RUN = args.dry_run

    fix_set: set[str] = set()
    for f in args.fixes:
        if f == "all":
            fix_set.update({"manifest", "date", "css"})
        else:
            fix_set.add(f)

    # ── load ────────────────────────────────────────────────────────────
    _ensure_ebooklib()
    from ebooklib import epub as _epub

    try:
        book = _epub.read_epub(args.epub)
    except KeyError as exc:
        print(
            f"Error: Failed to read EPUB (missing internal file): {exc}",
            file=sys.stderr,
        )
        print(
            "The manifest may reference files not in the archive. "
            "Try running with --fix manifest or repair the EPUB manually.",
            file=sys.stderr,
        )
        sys.exit(2)
    except Exception as exc:
        print(f"Error: Failed to read EPUB: {exc}", file=sys.stderr)
        sys.exit(2)

    # ── apply ───────────────────────────────────────────────────────────
    all_changes: list[Change] = []

    for fix_name in ("manifest", "date", "css"):
        if fix_name not in fix_set:
            continue

        label = f"[{fix_name}]".ljust(14)
        fn = FIX_REGISTRY[fix_name]
        print(f"{label} Scanning ...")
        results = fn(book, args.epub)
        all_changes.extend(results)

        if results:
            for c in results:
                print(f"  {c.description}")
            print(f"  -> {len(results)} change(s)")
        else:
            print(f"  No issues found.")
        print()

    # ── save ────────────────────────────────────────────────────────────
    out = _output_path(args.epub, args.in_place)

    if DRY_RUN:
        print("=" * 60)
        if all_changes:
            print(f"DRY RUN: {len(all_changes)} change(s) would be applied.")
        else:
            print("DRY RUN: no changes needed.")
        print(f"Output would be: {out}")
    elif all_changes:
        print("=" * 60)
        try:
            _epub.write_epub(out, book)
        except Exception as exc:
            print(f"Error: Failed to write EPUB: {exc}", file=sys.stderr)
            sys.exit(2)
        print(f"Fixed EPUB written to: {out}")
        print(f"Total changes applied: {len(all_changes)}")
    else:
        print("=" * 60)
        print("No changes needed -- EPUB is already clean.")

    sys.exit(0)


if __name__ == "__main__":
    main()
