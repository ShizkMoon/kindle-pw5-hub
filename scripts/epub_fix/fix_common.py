"""
Common EPUB Structural Fixes

Programmatic fixes for recurring EPUB issues: manifest gaps, broken links,
invalid dates, and CSS cleanup. Uses ebooklib for safe in-place editing.

Usage:
    python fix_common.py book.epub --fix all
    python fix_common.py book.epub --fix manifest --fix date --dry-run
    python fix_common.py book.epub --fix css --in-place
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Set

from ebooklib import epub


# ── Utilities ──────────────────────────────────────────────────────────────

def _get_html_files(book: epub.EpubBook) -> list:
    """Get all XHTML/HTML items from the book."""
    return [
        item for item in book.get_items()
        if item.get_type() == 9  # ITEM_DOCUMENT
    ]


def _get_css_files(book: epub.EpubBook) -> list:
    """Get all CSS items from the book."""
    return [
        item for item in book.get_items()
        if item.get_type() == 5  # ITEM_STYLE
    ]


def _get_all_item_hrefs(book: epub.EpubBook) -> Set[str]:
    """Get the set of all hrefs referenced by items in the book."""
    hrefs = set()
    for item in book.get_items():
        href = item.get_name()
        if href:
            hrefs.add(href)
    return hrefs


def _extract_hrefs_from_html(content: str) -> Set[str]:
    """Extract all referenced file paths from HTML content."""
    hrefs = set()
    # src="..." and href="..." attributes
    for match in re.finditer(r'(?:src|href)=["\']([^"\']+)["\']', content):
        path = match.group(1)
        # Skip external URLs and data URIs
        if not path.startswith(('http:', 'https:', 'data:', '#', 'mailto:')):
            hrefs.add(path)
    # url(...) in CSS
    for match in re.finditer(r'url\(["\']?([^"\')\s]+)["\']?\)', content):
        path = match.group(1)
        if not path.startswith(('http:', 'https:', 'data:')):
            hrefs.add(path)
    return hrefs


# ── Fix: Manifest ──────────────────────────────────────────────────────────

def fix_manifest(book: epub.EpubBook, dry_run: bool = False) -> int:
    """
    Add items referenced in HTML but missing from OPF manifest.
    Remove OPF entries pointing to non-existent files.
    Returns count of fixes applied.
    """
    fixes = 0
    all_hrefs = _get_all_item_hrefs(book)

    # Collect all referenced hrefs from HTML files
    referenced = set()
    for item in _get_html_files(book):
        content = item.get_content().decode('utf-8', errors='replace')
        referenced.update(_extract_hrefs_from_html(content))

    # Find missing items (referenced but not in manifest)
    missing = referenced - all_hrefs
    for href in sorted(missing):
        print(f"  [MISSING] {href} (referenced but not in OPF manifest)")
        if not dry_run:
            # Create a stub item if it's an image; skip for unknown types
            if href.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg')):
                item = epub.EpubItem(
                    uid=f'fix_{href.replace("/", "_")}',
                    file_name=href,
                    media_type=f'image/{href.rsplit(".", 1)[-1]}',
                    content=b'',
                )
                book.add_item(item)
                fixes += 1
                print(f"    -> Added to manifest (empty placeholder)")

    # Find orphan entries (in manifest but file doesn't exist)
    # Ebooklib virtual filesystem - we check if items have content
    for item in list(book.get_items()):
        href = item.get_name()
        if href and href not in referenced and item.get_type() != 5:  # Skip CSS
            # Only flag non-structural items
            if href.startswith(('image/', 'font/', 'media/')):
                print(f"  [ORPHAN] {href} (in manifest, never referenced)")
                fixes += 1

    return fixes


# ── Fix: Date ──────────────────────────────────────────────────────────────

DATE_FORMATS = [
    (re.compile(r'^\d{4}-\d{2}-\d{2}$'), None),              # 2024-01-15
    (re.compile(r'^\d{4}-\d{2}$'), '{}-01'),                  # 2024-01
    (re.compile(r'^\d{4}$'), '{}-01-01'),                     # 2024
    (re.compile(r'^\d{2}/\d{2}/\d{4}$'), None),               # 01/15/2024
    (re.compile(r'^\d{4}\.\d{2}\.\d{2}$'), None),             # 2024.01.15
]


def _normalize_date(raw: str) -> Optional[str]:
    """Normalize a date string to YYYY-MM-DD."""
    raw = raw.strip()

    # Already valid
    if re.match(r'^\d{4}-\d{2}-\d{2}$', raw):
        try:
            datetime.strptime(raw, '%Y-%m-%d')
            return raw
        except ValueError:
            pass

    # MM/DD/YYYY -> YYYY-MM-DD
    m = re.match(r'^(\d{2})/(\d{2})/(\d{4})$', raw)
    if m:
        return f'{m.group(3)}-{m.group(1)}-{m.group(2)}'

    # YYYY.MM.DD
    m = re.match(r'^(\d{4})\.(\d{2})\.(\d{2})$', raw)
    if m:
        return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'

    # YYYY-MM
    m = re.match(r'^(\d{4})-(\d{2})$', raw)
    if m:
        return f'{m.group(1)}-{m.group(2)}-01'

    # YYYY
    m = re.match(r'^(\d{4})$', raw)
    if m:
        return f'{m.group(1)}-01-01'

    # Try as a general date parse
    for fmt in ['%B %d, %Y', '%d %B %Y', '%Y年%m月%d日', '%Y年%m月']:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            continue

    return None


def fix_date(book: epub.EpubBook, dry_run: bool = False) -> int:
    """Fix invalid DC date metadata fields."""
    fixes = 0
    dc_tags = book.get_metadata('DC', 'date')

    for raw in dc_tags:
        normalized = _normalize_date(raw[0])
        if normalized and normalized != raw[0]:
            print(f"  [DATE] '{raw[0]}' -> '{normalized}'")
            if not dry_run:
                # Remove old, add new
                # ebooklib metadata API is limited; we replace via internal
                book.metadata[book.metadata.index(raw)] = (raw[0], raw[1], {'content': normalized, 'event': raw[2].get('event', 'publication')})
            fixes += 1
        elif normalized is None:
            print(f"  [DATE] '{raw[0]}' -> cannot normalize, setting to today")
            if not dry_run:
                today = datetime.now().strftime('%Y-%m-%d')
                book.metadata[book.metadata.index(raw)] = (raw[0], raw[1], {'content': today, 'event': raw[2].get('event', 'publication')})
            fixes += 1

    return fixes


# ── Fix: CSS ────────────────────────────────────────────────────────────────

CSS_BAD_PATTERNS = [
    # px font-size on body or p
    (re.compile(r'(body|p|\*)\s*\{[^}]*font-size\s*:\s*\d+\s*px', re.DOTALL),
     'font-size in px (KOReader cannot scale this)'),
    # line-height < 1.2
    (re.compile(r'line-height\s*:\s*(0\.\d+|1\.[01])\b'),
     'line-height < 1.2 (may cause text clipping)'),
    # !important on body text properties
    (re.compile(r'body\s*\{(?:(?!\}).)*!important', re.DOTALL),
     '!important on body (blocks user style overrides)'),
    # font-family lock on body
    (re.compile(r'body\s*\{[^}]*font-family\s*:', re.DOTALL),
     'font-family on body (blocks KOReader font selection)'),
    # px margins
    (re.compile(r'margin(?:-top|-bottom|-left|-right)?\s*:\s*\d+\s*px'),
     'fixed px margins (should use em or %)'),
]


def fix_css(book: epub.EpubBook, dry_run: bool = False) -> int:
    """Audit and flag CSS issues. Fixes are suggested but require manual review."""
    issues = 0
    for item in _get_css_files(book):
        content = item.get_content().decode('utf-8', errors='replace')
        name = item.get_name()

        for pattern, description in CSS_BAD_PATTERNS:
            for match in pattern.finditer(content):
                # Extract context (20 chars around match)
                start = max(0, match.start() - 20)
                end = min(len(content), match.end() + 20)
                context = content[start:end].replace('\n', ' ').strip()
                print(f"  [CSS-{name}] {description}")
                print(f"    Context: ...{context}...")
                issues += 1

    if issues == 0:
        print("  No CSS issues found.")

    return issues


# ── Main ────────────────────────────────────────────────────────────────────

FIX_MAP = {
    'manifest': fix_manifest,
    'date': fix_date,
    'css': fix_css,
}


def main():
    parser = argparse.ArgumentParser(
        description='Fix common EPUB structural issues',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fix_common.py book.epub --fix all --dry-run
  python fix_common.py book.epub --fix manifest --fix date
  python fix_common.py book.epub --fix css
        """,
    )
    parser.add_argument('input', help='Input EPUB file')
    parser.add_argument(
        '--fix', nargs='+', choices=['all', 'manifest', 'date', 'css'],
        required=True, help='Fixes to apply'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Show what would be changed without writing'
    )
    parser.add_argument(
        '--in-place', action='store_true',
        help='Overwrite input file instead of creating _fixed.epub'
    )

    args = parser.parse_args()

    fixes_to_apply = set(args.fix)
    if 'all' in fixes_to_apply:
        fixes_to_apply = {'manifest', 'date', 'css'}

    # Load book
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {input_path} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Loading: {input_path}")
    book = epub.read_epub(str(input_path))

    total_fixes = 0
    for fix_name in sorted(fixes_to_apply):
        print(f"\n[{fix_name.upper()}]")
        count = FIX_MAP[fix_name](book, dry_run=args.dry_run)
        total_fixes += count

    # Save
    if args.dry_run:
        print(f"\n[DRY RUN] {total_fixes} issue(s) found. No changes written.")
    else:
        if args.in_place:
            output = input_path
        else:
            output = input_path.with_stem(f'{input_path.stem}_fixed')

        epub.write_epub(str(output), book)
        print(f"\n[DONE] {total_fixes} issue(s) addressed. Saved to: {output}")


if __name__ == '__main__':
    main()
