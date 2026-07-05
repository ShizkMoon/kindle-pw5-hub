from __future__ import annotations

import html
import re
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
    normalized = re.sub(r"[^\w.-]+", "-", canonical_id_for(job.title, job.author)).strip("-")
    return "urn:hermes:" + (normalized or job.id)


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
        body = [f'<h2 id="title">{html.escape(title)}</h2>']
        for para_idx, line in enumerate(ch["content_lines"], start=1):
            stripped = line.strip()
            if stripped:
                body.append(f'<p id="p{para_idx:04d}">{html.escape(stripped)}</p>')
        chapter = epub.EpubHtml(title=title, file_name=_chapter_file(idx), lang="zh")
        chapter.content = (
            "<?xml version='1.0' encoding='utf-8'?>\n"
            "<!DOCTYPE html>\n"
            "<html xmlns='http://www.w3.org/1999/xhtml' xml:lang='zh'>"
            "<head><title>{}</title><link rel='stylesheet' type='text/css' href='../styles/standard.css'/></head>"
            "<body>{}</body></html>"
        ).format(html.escape(title), "\n".join(body)).encode("utf-8")
        chapter.add_link(href="../styles/standard.css", rel="stylesheet", type="text/css")
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
