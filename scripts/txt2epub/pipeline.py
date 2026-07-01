"""
TXT → EPUB Processing Pipeline

Full automated pipeline for converting raw TXT files (especially Chinese web novels)
to professional-quality EPUB files suitable for KOReader.

Usage:
    python pipeline.py input.txt -t "Book Title" -a "Author Name"
    python pipeline.py input.txt -t "Title" --s2t --ai-chapter

Dependencies:
    pip install ebooklib charset-normalizer opencc
"""

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Optional

import charset_normalizer
from ebooklib import epub


# ── Chapter Detection ──────────────────────────────────────────────────────

CHAPTER_PATTERNS = [
    # Chinese: 第X章, 第X回, 第X卷, 第X节, 第X部, 第X集, 第X篇
    re.compile(r'^第[0-9零一二三四五六七八九十百千万]+[章回卷节部集篇].*$'),
    # English: Chapter X, Part X, Book X
    re.compile(r'^(?:Chapter|Part|Book|Volume)\s+\d+.*$', re.IGNORECASE),
    # Roman numerals: Part I, Book II
    re.compile(r'^(?:Part|Book)\s+[IVX]+.*$', re.IGNORECASE),
    # Numbered: 1. Title, 1、Title
    re.compile(r'^\d+[\.\、\s]+.+$'),
]

# Website garbage patterns (configurable)
GARBAGE_PATTERNS = [
    re.compile(r'本章未完.*请点击'),
    re.compile(r'记住本站.*'),
    re.compile(r'https?://\S+'),
    re.compile(r'最新章节.*'),
    re.compile(r'手机阅读.*'),
    re.compile(r'[\(（][^)）]*[求更求票求收藏求推荐][^)）]*[\)）]'),
    re.compile(r'^[~=_\-]{5,}$'),        # Separator lines
    re.compile(r'^\s*\d+\s*$'),           # Standalone numbers
]


def detect_encoding(filepath: str) -> str:
    """Auto-detect text file encoding."""
    with open(filepath, 'rb') as f:
        raw = f.read()
    result = charset_normalizer.from_bytes(raw).best()
    if result is None:
        raise ValueError(f"Cannot detect encoding for {filepath}")
    return result.encoding


def read_text(filepath: str) -> str:
    """Read text file with auto encoding detection."""
    encoding = detect_encoding(filepath)
    with open(filepath, 'r', encoding=encoding, errors='replace') as f:
        return f.read()


def detect_chapters(text: str) -> list[dict]:
    """
    Detect chapter structure from text.
    Returns list of {index, title, content_lines, start_line}.
    """
    lines = text.split('\n')
    chapter_boundaries = []

    for i, line in enumerate(lines):
        line = line.strip()
        for pat in CHAPTER_PATTERNS:
            if pat.match(line):
                # Skip if line is too long (probably not a real chapter title)
                if len(line) > 60:
                    continue
                chapter_boundaries.append({
                    'line_index': i,
                    'title': line,
                })
                break

    if not chapter_boundaries:
        # Fallback: treat entire text as one chapter
        return [{'index': 0, 'title': '正文', 'content_lines': lines, 'start_line': 0}]

    chapters = []
    for idx, boundary in enumerate(chapter_boundaries):
        start = boundary['line_index']
        end = chapter_boundaries[idx + 1]['line_index'] if idx + 1 < len(chapter_boundaries) else len(lines)
        content = lines[start + 1:end]  # Exclude title line
        chapters.append({
            'index': idx,
            'title': boundary['title'],
            'content_lines': content,
            'start_line': start,
        })

    # Handle pre-first-chapter content as "简介"
    first_start = chapter_boundaries[0]['line_index']
    if first_start > 0:
        intro_content = [l for l in lines[:first_start] if l.strip()]
        if intro_content:
            chapters.insert(0, {
                'index': -1,
                'title': '简介',
                'content_lines': intro_content,
                'start_line': 0,
            })

    return chapters


def filter_garbage(lines: list[str]) -> list[str]:
    """Remove website garbage and ad lines."""
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue
        if any(pat.search(stripped) for pat in GARBAGE_PATTERNS):
            continue
        cleaned.append(line)
    return cleaned


def merge_hard_linebreaks(lines: list[str]) -> list[str]:
    """
    Merge single hard linebreaks within Chinese paragraphs.
    Criteria: previous line ends with CJK/punctuation, next line starts with CJK.
    """
    CJK_RANGE = (
        '\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff'
        '\u3000-\u303f\uff00-\uffef\u2e80-\u2eff\u31c0-\u31ef'
    )
    cjk_char = re.compile(f'[{CJK_RANGE}]')
    cjk_end = re.compile(f'[{CJK_RANGE}〕》）」』】"\'\\-]$')
    cjk_start = re.compile(f'^[{CJK_RANGE}〔《（「『【]')

    merged = []
    buffer = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if buffer:
                merged.append(''.join(buffer))
                buffer = []
            merged.append(line)
            continue

        if buffer:
            prev = buffer[-1].rstrip()
            if cjk_end.search(prev) and cjk_start.search(stripped):
                # Merge: remove newline, join directly
                buffer.append(stripped)
            elif cjk_end.search(prev) and cjk_char.match(stripped):
                buffer.append(stripped)
            else:
                merged.append(''.join(buffer))
                buffer = [line]
        else:
            buffer = [line]

    if buffer:
        merged.append(''.join(buffer))
    return merged


def normalize_paragraphs(lines: list[str]) -> list[str]:
    """Normalize paragraph formatting."""
    result = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            result.append('')
            continue
        # Remove leading whitespace (replaced by CSS text-indent)
        result.append(stripped)
    return result


def ai_chapter_detect(text_sample: str) -> Optional[dict]:
    """
    Use AI to detect chapter structure when regex fails.
    Requires NEW_API_URL and NEW_API_KEY environment variables.
    """
    api_url = os.environ.get('NEW_API_URL')
    api_key = os.environ.get('NEW_API_KEY')
    if not api_url or not api_key:
        return None

    import urllib.request

    prompt = f"""Analyze this Chinese text and identify its chapter structure.
Return ONLY valid JSON, no other text:
{{
  "format": "chinese_chapter" | "english_chapter" | "no_structure",
  "chapter_pattern": "regex string that matches chapter titles",
  "sample_matches": ["matched line 1", "matched line 2"],
  "has_volume": true/false,
  "has_prologue": true/false
}}

Text sample (first 3000 chars):
{text_sample[:3000]}"""

    try:
        req = urllib.request.Request(
            f"{api_url}/v1/chat/completions",
            data=json.dumps({
                "model": "glm-4.7",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 500,
            }).encode(),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            content = data['choices'][0]['message']['content']
            # Extract JSON from response (may have markdown fences)
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
    except Exception:
        pass
    return None


# ── EPUB Building ──────────────────────────────────────────────────────────

STANDARD_CSS = """
/* === Base === */
body {
  line-height: 1.5;
  text-align: justify;
  margin: 0;
  padding: 0;
  widows: 1;
  orphans: 1;
  hyphens: auto;
  -webkit-hyphens: auto;
  -epub-hyphens: auto;
  hyphenate-limit-chars: 6 3 2;
  hyphenate-limit-lines: 2;
  font-kerning: normal;
  font-variant-numeric: oldstyle-nums proportional-nums;
}

/* === Paragraphs === */
p {
  margin-top: 0;
  margin-bottom: 0;
  text-indent: 2em;
}
p + p {
  margin-top: 0.3em;
}

/* No indent after headings and breaks */
h1 + p, h2 + p, h3 + p, .section-break + p {
  text-indent: 0;
}

/* === Headings === */
h1 {
  text-align: center;
  font-size: 2em;
  margin: 3em 0 1em 0;
}
h2 {
  text-align: center;
  font-size: 1.5em;
  margin: 2em 0 0.5em 0;
}
h3 {
  text-align: left;
  font-size: 1.3em;
  margin: 1.5em 0 0.5em 0;
}

/* === Blockquotes === */
blockquote {
  margin: 1em 5%;
  font-size: 0.95em;
}

/* === Images === */
img {
  max-width: 100%;
  height: auto;
}

/* === Small caps (real OpenType, not fake) === */
.small-caps {
  font-variant-caps: small-caps;
  letter-spacing: 0.05em;
}

/* === Tables === */
table {
  max-width: 100%;
  border-collapse: collapse;
}
"""


def build_epub(
    chapters: list[dict],
    title: str,
    author: str,
    language: str = 'zh',
    cover_path: Optional[str] = None,
) -> epub.EpubBook:
    """Build EPUB from chapter data."""
    book = epub.EpubBook()

    # Metadata
    book.set_identifier(f'urn:uuid:{uuid.uuid4()}')
    book.set_title(title)
    book.set_language(language)
    book.add_author(author)
    book.add_metadata('DC', 'date', '2026-01-01')

    # CSS
    css_item = epub.EpubItem(
        uid='standard-css',
        file_name='style/standard.css',
        media_type='text/css',
        content=STANDARD_CSS.encode('utf-8'),
    )
    book.add_item(css_item)

    # Cover
    if cover_path and os.path.exists(cover_path):
        with open(cover_path, 'rb') as f:
            book.set_cover('cover.jpg', f.read())

    # Chapters
    spine = ['nav']
    toc_entries = []

    for ch in chapters:
        ch_id = f'ch{ch["index"]:03d}'
        ch_title = ch['title']
        ch_file = f'{ch_id}.xhtml'

        # Build HTML body
        body_parts = [f'<h3>{ch_title}</h3>']
        for line in ch['content_lines']:
            stripped = line.strip()
            if not stripped:
                body_parts.append('<p class="section-break">&nbsp;</p>')
            else:
                body_parts.append(f'<p>{stripped}</p>')

        html_content = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{language}">
<head>
  <title>{ch_title}</title>
  <link rel="stylesheet" type="text/css" href="style/standard.css"/>
</head>
<body>
  {'\n  '.join(body_parts)}
</body>
</html>"""

        chapter = epub.EpubHtml(
            title=ch_title,
            file_name=ch_file,
            lang=language,
        )
        chapter.content = html_content.encode('utf-8')
        chapter.add_item(css_item)
        book.add_item(chapter)
        spine.append(chapter)
        toc_entries.append(epub.Link(ch_file, ch_title, ch_id))

    # Navigation
    book.toc = (epub.Section('目录'), toc_entries)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine

    return book


def convert_to_simplified(text: str) -> str:
    """Convert Traditional Chinese to Simplified using OpenCC."""
    try:
        import opencc
        cc = opencc.OpenCC('t2s.json')
        return cc.convert(text)
    except ImportError:
        print("Warning: opencc not installed, skipping conversion", file=sys.stderr)
        return text


def convert_to_traditional(text: str) -> str:
    """Convert Simplified Chinese to Traditional using OpenCC."""
    try:
        import opencc
        cc = opencc.OpenCC('s2t.json')
        return cc.convert(text)
    except ImportError:
        print("Warning: opencc not installed, skipping conversion", file=sys.stderr)
        return text


# ── Main Pipeline ──────────────────────────────────────────────────────────

def pipeline(
    input_path: str,
    title: str,
    author: str,
    output_path: Optional[str] = None,
    s2t: bool = False,
    t2s: bool = False,
    ai_chapter: bool = False,
    cover: Optional[str] = None,
    language: str = 'zh',
) -> str:
    """
    Execute the full TXT → EPUB pipeline.

    Args:
        input_path: Path to input TXT file
        title: Book title
        author: Author name
        output_path: Output EPUB path (default: input_stem.epub)
        s2t: Convert Simplified to Traditional
        t2s: Convert Traditional to Simplified
        ai_chapter: Use AI for chapter detection if regex fails
        cover: Path to cover image
        language: EPUB language code

    Returns:
        Path to generated EPUB file
    """
    if output_path is None:
        output_path = Path(input_path).with_suffix('.epub')

    print(f"[1/7] Reading: {input_path}")
    text = read_text(input_path)
    print(f"      Encoding: {detect_encoding(input_path)}, Chars: {len(text)}")

    print("[2/7] Chapter detection...")
    chapters = detect_chapters(text)

    if not chapters or all(ch['title'] == '正文' for ch in chapters):
        if ai_chapter:
            print("      Regex failed, trying AI...")
            ai_result = ai_chapter_detect(text)
            if ai_result and ai_result.get('chapter_pattern'):
                pattern = ai_result['chapter_pattern']
                print(f"      AI detected pattern: {pattern}")
                CHAPTER_PATTERNS.insert(0, re.compile(pattern))
                chapters = detect_chapters(text)

    # Remove the "简介" if it's empty
    chapters = [ch for ch in chapters if any(l.strip() for l in ch['content_lines'])]
    print(f"      Found {len(chapters)} chapters/sections")

    print("[3/7] Cleaning content...")
    for ch in chapters:
        ch['content_lines'] = filter_garbage(ch['content_lines'])
        ch['content_lines'] = merge_hard_linebreaks(ch['content_lines'])
        ch['content_lines'] = normalize_paragraphs(ch['content_lines'])

    # Flatten text for OpenCC
    if s2t or t2s:
        print(f"[4/7] Character conversion ({'S2T' if s2t else 'T2S'})...")
        converter = convert_to_traditional if s2t else convert_to_simplified
        for ch in chapters:
            new_lines = []
            for line in ch['content_lines']:
                new_lines.append(converter(line) if line.strip() else line)
            ch['content_lines'] = new_lines
    else:
        print("[4/7] Skipping character conversion")

    print("[5/7] Building EPUB...")
    book = build_epub(chapters, title, author, language, cover)

    print(f"[6/7] Writing: {output_path}")
    epub.write_epub(str(output_path), book)

    size_kb = os.path.getsize(output_path) / 1024
    print(f"[7/7] Done: {output_path} ({size_kb:.0f} KB, {len(chapters)} chapters)")

    return str(output_path)


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='TXT → EPUB Pipeline for KOReader',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pipeline.py novel.txt -t "三体" -a "刘慈欣"
  python pipeline.py novel.txt -t "Title" -a "Author" --ai-chapter --s2t
  python pipeline.py novel.txt -t "Title" -a "Author" --cover cover.jpg
        """,
    )
    parser.add_argument('input', help='Input TXT file')
    parser.add_argument('-t', '--title', required=True, help='Book title')
    parser.add_argument('-a', '--author', required=True, help='Author name')
    parser.add_argument('-o', '--output', help='Output EPUB path')
    parser.add_argument('--s2t', action='store_true', help='Simplified → Traditional')
    parser.add_argument('--t2s', action='store_true', help='Traditional → Simplified')
    parser.add_argument('--ai-chapter', action='store_true', help='Use AI for chapter detection')
    parser.add_argument('--cover', help='Cover image path')
    parser.add_argument('--lang', default='zh', help='Language code (default: zh)')

    args = parser.parse_args()

    try:
        output = pipeline(
            input_path=args.input,
            title=args.title,
            author=args.author,
            output_path=args.output,
            s2t=args.s2t,
            t2s=args.t2s,
            ai_chapter=args.ai_chapter,
            cover=args.cover,
            language=args.lang,
        )
        print(f"\n✓ EPUB generated: {output}")
    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
