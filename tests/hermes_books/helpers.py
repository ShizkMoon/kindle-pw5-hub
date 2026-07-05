from __future__ import annotations

from pathlib import Path

from ebooklib import epub


def make_epub(
    path: Path,
    title: str = "Book",
    author: str = "Author",
    chapters: list[tuple[str, str]] | None = None,
    chapter_file_names: list[str] | None = None,
    css: str = "p { text-indent: 2em; }",
    cover_file_name: str | None = None,
) -> Path:
    if chapters is None:
        chapters = [("第一章", "第一章正文"), ("第二章", "第二章正文")]
    book = epub.EpubBook()
    book.set_identifier("urn:test:book-author")
    book.set_title(title)
    book.set_language("zh")
    book.add_author(author)

    css_item = epub.EpubItem(
        uid="style",
        file_name="styles/style.css",
        media_type="text/css",
        content=css.encode("utf-8"),
    )
    book.add_item(css_item)

    spine: list[object] = ["nav"]
    toc: list[object] = []
    for idx, (chapter_title, text) in enumerate(chapters, start=1):
        file_name = (
            chapter_file_names[idx - 1]
            if chapter_file_names is not None
            else f"chapters/ch{idx:04d}.xhtml"
        )
        chapter = epub.EpubHtml(
            title=chapter_title,
            file_name=file_name,
            lang="zh",
        )
        chapter.content = (
            "<?xml version='1.0' encoding='utf-8'?>\n"
            "<!DOCTYPE html>\n"
            "<html xmlns='http://www.w3.org/1999/xhtml' xml:lang='zh'>"
            "<head><title>{}</title><link rel='stylesheet' type='text/css' href='../styles/style.css'/></head>"
            "<body><h2>{}</h2><p>{}</p></body></html>"
        ).format(chapter_title, chapter_title, text).encode("utf-8")
        chapter.add_link(href="../styles/style.css", rel="stylesheet", type="text/css")
        book.add_item(chapter)
        spine.append(chapter)
        toc.append(epub.Link(chapter.file_name, chapter_title, f"ch{idx:04d}"))

    if cover_file_name is not None:
        book.set_cover(cover_file_name, b"fake image bytes", create_page=False)

    book.toc = toc
    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(path), book)
    return path
