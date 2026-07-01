#!/usr/bin/env python3
"""
基于 ISBN 的元数据充实工具。

从免费公共 API（Open Library、Google Books）获取图书元数据，
并输出结构化 JSON 或可读文本。可选地，可通过 calibredb
将元数据直接推送到 Calibre 书库。

用法:
    python enrich.py --isbn 9787544270878
    python enrich.py --isbn 9787544270878 --format text
    python enrich.py --title "Book Title" --author "Author Name"
    python enrich.py --isbn 9787544270878 --output calibre
    python enrich.py --isbn 9787544270878 --output calibre --format json

环境变量（可选 / 增强功能）:
    NEW_API_URL  - AI 合并/验证端点的 URL
    NEW_API_KEY  - AI 端点的 Bearer 令牌
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OPEN_LIBRARY_ISBN_URL = "https://openlibrary.org/isbn/{isbn}.json"
OPEN_LIBRARY_BOOKS_URL = (
    "https://openlibrary.org/api/books"
    "?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
)
GOOGLE_BOOKS_URL = (
    "https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"
)

# Standard ISBN regex (ISBN-10 / ISBN-13 with optional hyphens/spaces)
import re

_ISBN_RE = re.compile(
    r"^(?:ISBN(?:-1[03])?:?\s*)?(?=[-0-9X\s]{10,17}$)"
    r"(?:97[89][- ]?)?[0-9]{1,5}[- ]?[0-9]+[- ]?[0-9]+[- ]?[0-9Xx]$"
)

# User-Agent sent with all HTTP requests
USER_AGENT = "kindle-pw5-enrich/1.0 (book-metadata-tool)"

# Maximum retries for rate-limited requests
MAX_RETRIES = 5
# Base backoff in seconds
BASE_BACKOFF = 2.0


# ---------------------------------------------------------------------------
# 字段标签映射（仅用于文本输出模式）
# ---------------------------------------------------------------------------

_FIELD_LABELS: Dict[str, str] = {
    "isbn": "ISBN",
    "title": "标题",
    "authors": "作者",
    "publisher": "出版社",
    "published_date": "出版日期",
    "page_count": "页数",
    "description": "简介",
    "subjects": "主题",
    "cover_url": "封面链接",
}

_SOURCE_LABELS: Dict[str, str] = {
    "openlibrary_isbn": "Open Library ISBN",
    "openlibrary_books": "Open Library 图书",
    "google_books": "Google Books",
    "openlibrary_search": "Open Library 搜索",
    "user": "用户提供",
    "ai_merged": "AI 合并",
    "search_fallback": "搜索回退",
    "unknown": "未知",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise_isbn(raw: str) -> str:
    """去除连字符、空格和 'ISBN' 前缀；返回纯数字。"""
    s = raw.strip().upper()
    s = re.sub(r"^ISBN(?:-1[03])?:?\s*", "", s, flags=re.IGNORECASE)
    s = s.replace("-", "").replace(" ", "")
    return s


def _fetch_json(url: str) -> Optional[Any]:
    """GET *url*，解析 JSON，遇到 429/5xx 时带指数退避重试。"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503):
                wait = BASE_BACKOFF ** attempt
                sys.stderr.write(
                    f"[enrich] HTTP {exc.code} – {wait:.1f}秒后重试"
                    f"（第 {attempt}/{MAX_RETRIES} 次尝试）\n"
                )
                time.sleep(wait)
                continue
            sys.stderr.write(f"[enrich] {url} 返回 HTTP {exc.code}\n")
            return None
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            sys.stderr.write(f"[enrich] 请求失败: {exc}\n")
            return None
    sys.stderr.write(f"[enrich] {url} 重试次数已用完\n")
    return None


# ---------------------------------------------------------------------------
# API-sourcing context manager – records which API each field came from
# ---------------------------------------------------------------------------

class SourcedData:
    """保存最终的结构化元数据及每个字段的来源。"""

    def __init__(self) -> None:
        self.data: Dict[str, Any] = {}
        self.sources: Dict[str, str] = {}

    def set_field(
        self, key: str, value: Any, source: str, *, overwrite: bool = False
    ) -> None:
        """将 *value* 存入 *key* 并记录其 *source*。

        默认情况下，已有值不会被覆盖（先到先得）。
        传入 *overwrite=True* 可强制更新。
        """
        if key in self.data and not overwrite:
            return
        self.data[key] = value
        self.sources[key] = source

    def as_output(self, format: str = "json") -> str:
        """将元数据渲染为 JSON 或可读文本。"""
        if format == "json":
            result: Dict[str, Any] = {
                "metadata": self.data,
                "sources": self.sources,
            }
            return json.dumps(result, ensure_ascii=False, indent=2)
        # -- text / human-readable
        lines: List[str] = []
        for key, val in self.data.items():
            label = _FIELD_LABELS.get(key, key)
            src = self.sources.get(key, "unknown")
            src_label = _SOURCE_LABELS.get(src, src)
            if isinstance(val, list):
                lines.append(f"{label}:")
                for item in val:
                    lines.append(f"  - {item}")
            else:
                lines.append(f"{label}: {val}")
            lines.append(f"  ^-- 来源: {src_label}")
            lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_open_library_isbn(isbn: str) -> Optional[Dict[str, Any]]:
    """获取 Open Library /isbn/{isbn}.json 端点。"""
    url = OPEN_LIBRARY_ISBN_URL.format(isbn=isbn)
    return _fetch_json(url)


def fetch_open_library_books(isbn: str) -> Optional[Dict[str, Any]]:
    """获取 Open Library /api/books 端点（更丰富的数据）。"""
    url = OPEN_LIBRARY_BOOKS_URL.format(isbn=isbn)
    return _fetch_json(url)


def fetch_google_books(isbn: str) -> Optional[Dict[str, Any]]:
    """获取 Google Books API volumes 端点。"""
    url = GOOGLE_BOOKS_URL.format(isbn=isbn)
    return _fetch_json(url)


def fetch_open_library_search(
    title: str, author: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """无 ISBN 时通过 Open Library 搜索 API 进行回退搜索。"""
    q = f"title:{title}"
    if author:
        q += f" author:{author}"
    params = urllib.parse.urlencode({"q": q, "limit": 3})
    url = f"https://openlibrary.org/search.json?{params}"
    return _fetch_json(url)


def fetch_google_books_search(
    title: str, author: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """无 ISBN 时通过 Google Books 进行回退搜索。"""
    q = f'intitle:"{title}"'
    if author:
        q += f' inauthor:"{author}"'
    params = urllib.parse.urlencode({"q": q, "maxResults": 3})
    url = f"https://www.googleapis.com/books/v1/volumes?{params}"
    return _fetch_json(url)


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def extract_open_library_isbn(
    data: Dict[str, Any]
) -> Tuple[Dict[str, Any], List[Tuple[str, str]]]:
    """从 /isbn/{isbn}.json 载荷中提取字段。"""
    fields: Dict[str, Any] = {}
    provenance: List[Tuple[str, str]] = []
    src = "openlibrary_isbn"

    _map_simple(data, fields, provenance, src, {
        "title": "title",
        "publish_date": "published_date",
        "number_of_pages": "page_count",
    })

    # publisher -> publishers array
    if "publishers" in data and data["publishers"]:
        fields["publisher"] = data["publishers"][0]
        provenance.append(("publisher", src))

    # description from multiple possible fields
    for desc_key in ("description", "first_sentence"):
        if data.get(desc_key):
            if isinstance(data[desc_key], dict):
                fields["description"] = data[desc_key].get("value", "")
            else:
                fields["description"] = str(data[desc_key])
            provenance.append(("description", src))
            break

    # subjects
    if "subjects" in data:
        fields["subjects"] = data["subjects"][:10]
        provenance.append(("subjects", src))

    # authors
    if "authors" in data:
        fields["authors"] = [
            a.get("name", str(a)) if isinstance(a, dict) else str(a)
            for a in data["authors"]
        ]
        provenance.append(("authors", src))

    # cover
    covers = data.get("covers")
    if covers:
        fields["cover_url"] = f"https://covers.openlibrary.org/b/id/{covers[0]}-L.jpg"
        provenance.append(("cover_url", src))

    return fields, provenance


def extract_open_library_books(
    isbn: str, data: Dict[str, Any]
) -> Tuple[Dict[str, Any], List[Tuple[str, str]]]:
    """从 /api/books 载荷中提取字段。"""
    fields: Dict[str, Any] = {}
    provenance: List[Tuple[str, str]] = []
    src = "openlibrary_books"
    key = f"ISBN:{isbn}"

    record = data.get(key, {})
    if not record:
        return fields, provenance

    if "title" in record:
        fields["title"] = record["title"]
        provenance.append(("title", src))

    if "publish_date" in record:
        fields["published_date"] = record["publish_date"]
        provenance.append(("published_date", src))

    if "number_of_pages" in record:
        try:
            fields["page_count"] = int(record["number_of_pages"])
        except (ValueError, TypeError):
            fields["page_count"] = record["number_of_pages"]
        provenance.append(("page_count", src))

    if "publishers" in record:
        fields["publisher"] = record["publishers"][0].get(
            "name", str(record["publishers"][0])
        )
        provenance.append(("publisher", src))

    if "authors" in record:
        fields["authors"] = [
            a.get("name", str(a)) if isinstance(a, dict) else str(a)
            for a in record["authors"]
        ]
        provenance.append(("authors", src))

    # description from notes/excerpts
    for desc_key in ("notes", "by_statement", "excerpts"):
        val = record.get(desc_key)
        if val:
            if isinstance(val, list):
                text = val[0].get("text", str(val[0])) if val else ""
            elif isinstance(val, dict):
                text = val.get("value", str(val))
            else:
                text = str(val)
            if text.strip():
                fields["description"] = text.strip()
                provenance.append(("description", src))
                break

    # subjects
    if "subjects" in record:
        fields["subjects"] = [
            s.get("name", str(s)) if isinstance(s, dict) else str(s)
            for s in record["subjects"][:10]
        ]
        provenance.append(("subjects", src))

    # cover
    if "cover" in record and record["cover"]:
        cov = record["cover"]
        if isinstance(cov, dict):
            fields["cover_url"] = cov.get("large") or cov.get("medium")
        else:
            fields["cover_url"] = str(cov)
        if "cover_url" in fields:
            provenance.append(("cover_url", src))

    return fields, provenance


def extract_google_books(
    data: Dict[str, Any]
) -> Tuple[Dict[str, Any], List[Tuple[str, str]]]:
    """从 Google Books API volumes 载荷中提取字段。"""
    fields: Dict[str, Any] = {}
    provenance: List[Tuple[str, str]] = []
    src = "google_books"

    items = data.get("items")
    if not items:
        return fields, provenance

    volume = items[0]
    vi = volume.get("volumeInfo", {})

    _map_simple(vi, fields, provenance, src, {
        "title": "title",
        "publisher": "publisher",
        "publishedDate": "published_date",
        "description": "description",
        "pageCount": "page_count",
    })

    if "authors" in vi:
        fields["authors"] = vi["authors"]
        provenance.append(("authors", src))

    if "categories" in vi:
        fields["subjects"] = vi["categories"]
        provenance.append(("subjects", src))

    # industry identifiers -> ISBN list to find the correct one
    ids = vi.get("industryIdentifiers", [])
    for ident in ids:
        if ident.get("type") in ("ISBN_13", "ISBN_10"):
            fields.setdefault("isbn", ident["identifier"])
            provenance.append(("isbn", src))

    # cover
    il = vi.get("imageLinks", {})
    if il:
        # Prefer thumbnail, fall back to smallThumbnail (no zoom needed for free tier)
        for covk in ("thumbnail", "smallThumbnail"):
            if il.get(covk):
                fields["cover_url"] = il[covk].replace(
                    "&edge=curl", ""
                ).replace("http:", "https:")
                provenance.append(("cover_url", src))
                break

    return fields, provenance


def extract_open_library_search(
    data: Dict[str, Any]
) -> Tuple[Dict[str, Any], List[Tuple[str, str]]]:
    """从 Open Library /search.json 中提取字段。"""
    fields: Dict[str, Any] = {}
    provenance: List[Tuple[str, str]] = []
    src = "openlibrary_search"

    docs = data.get("docs")
    if not docs:
        return fields, provenance

    doc = docs[0]

    _map_simple(doc, fields, provenance, src, {
        "title": "title",
        "publisher": "publisher",
        "first_publish_year": "published_date",
    })

    if "author_name" in doc:
        fields["authors"] = doc["author_name"]
        provenance.append(("authors", src))

    if "isbn" in doc:
        fields["isbn"] = doc["isbn"][0] if isinstance(doc["isbn"], list) else doc["isbn"]
        provenance.append(("isbn", src))

    if "subject" in doc:
        fields["subjects"] = doc["subject"][:10]
        provenance.append(("subjects", src))

    return fields, provenance


def extract_google_books_search(
    data: Dict[str, Any]
) -> Tuple[Dict[str, Any], List[Tuple[str, str]]]:
    """从 Google Books 搜索结果中提取字段。"""
    return extract_google_books(data)  # Same payload structure


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _map_simple(
    source: Dict[str, Any],
    target: Dict[str, Any],
    prov: List[Tuple[str, str]],
    src_name: str,
    mapping: Dict[str, str],
) -> None:
    """使用 *mapping* 将键从 *source* 字典复制到 *target* 字典，并记录来源。

    *mapping* 的格式为 {源键: 目标键}。
    """
    for sk, tk in mapping.items():
        if sk in source and source[sk] is not None:
            target[tk] = source[sk]
            prov.append((tk, src_name))


def _apply_fields(sd: SourcedData, fields: Dict[str, Any], prov: List[Tuple[str, str]]) -> None:
    """将提取的字段和来源信息填充到 SourcedData 容器中。"""
    for key, value in fields.items():
        sd.set_field(key, value, "unknown")
    for key, src in prov:
        sd.sources[key] = src


# ---------------------------------------------------------------------------
# AI merge (bonus)
# ---------------------------------------------------------------------------

def ai_merge_validate(sd: SourcedData) -> Optional[SourcedData]:
    """如果设置了 NEW_API_URL + NEW_API_KEY，将当前元数据 POST 到 AI
    端点，该端点返回已验证/合并的数据。

    端点应接受如下 JSON：
        {"metadata": ..., "sources": ...}
    并返回：
        {"metadata": ..., "sources": ...}
    """
    api_url = os.environ.get("NEW_API_URL")
    api_key = os.environ.get("NEW_API_KEY")
    if not api_url or not api_key:
        return None

    payload = json.dumps({
        "metadata": sd.data,
        "sources": sd.sources,
    }).encode("utf-8")

    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        sys.stderr.write(f"[enrich] AI 合并调用失败: {exc}\n")
        return None

    new_sd = SourcedData()
    for k, v in result.get("metadata", {}).items():
        new_sd.set_field(k, v, "ai_merged", overwrite=True)
    for k, v in result.get("sources", {}).items():
        new_sd.sources[k] = v
    return new_sd


# ---------------------------------------------------------------------------
# Calibre integration
# ---------------------------------------------------------------------------

def push_to_calibre(sd: SourcedData, isbn: str) -> int:
    """按 ISBN 在 Calibre 书库中查找图书，并通过 ``calibredb`` CLI
    更新其元数据。

    成功返回 0，失败返回非零。
    """
    # 1) 查找图书
    try:
        result = subprocess.run(
            ["calibredb", "search", f"isbn:{isbn}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        sys.stderr.write(
            "[enrich] 错误: 未找到 calibredb。Calibre 是否已安装"
            "并在 PATH 中？\n"
        )
        return 1
    except subprocess.TimeoutExpired:
        sys.stderr.write("[enrich] 错误: calibredb 搜索超时。\n")
        return 1

    if result.returncode != 0 or not result.stdout.strip():
        sys.stderr.write(
            f"[enrich] 未找到 ISBN 为 {isbn} 的 Calibre 图书。"
            f"请先将图书添加到 Calibre。\n"
        )
        return 1

    book_ids = result.stdout.strip().splitlines()
    if len(book_ids) > 1:
        sys.stderr.write(
            f"[enrich] 多个图书匹配 ISBN {isbn}，使用第一个: "
            f"{book_ids[0]}\n"
        )
    book_id = book_ids[0].strip()

    # 2) 构建 set-metadata 参数
    args = ["calibredb", "set_metadata", book_id]
    md = sd.data

    if md.get("title"):
        args.extend(["--title", str(md["title"])])
    if md.get("authors"):
        args.extend(["-a"] + [str(a) for a in md["authors"]])
    if md.get("publisher"):
        args.extend(["--publisher", str(md["publisher"])])
    if md.get("published_date"):
        args.extend(["--date", str(md["published_date"])])
    if md.get("description"):
        args.extend(["--comment", str(md["description"])])
    if md.get("subjects"):
        args.extend(["-t"] + [str(s) for s in md["subjects"]])

    if len(args) <= 3:
        sys.stderr.write("[enrich] 没有可推送到 Calibre 的元数据字段。\n")
        return 0

    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        sys.stderr.write("[enrich] 错误: calibredb set_metadata 超时。\n")
        return 1

    if proc.returncode != 0:
        sys.stderr.write(
            f"[enrich] calibredb 错误: {proc.stderr or proc.stdout}\n"
        )
        return proc.returncode

    sys.stderr.write(
        f"[enrich] 已成功更新图书 {book_id} 的 Calibre 元数据。\n"
    )
    return 0


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def enrich(
    isbn: Optional[str] = None,
    title: Optional[str] = None,
    author: Optional[str] = None,
    *,
    output_mode: str = "stdout",
    format: str = "json",
) -> int:
    """运行完整的元数据充实流水线。

    成功返回 0，失败返回非零。
    """
    sd = SourcedData()
    norm_isbn = _normalise_bookid(isbn) if isbn else None

    # ------------------------------------------------------------------
    # 1. ISBN 查找
    # ------------------------------------------------------------------
    if norm_isbn:
        sd.set_field("isbn", norm_isbn, "user")

        # 1a. Open Library /isbn/{isbn}
        ol_isbn = fetch_open_library_isbn(norm_isbn)
        if ol_isbn:
            fields, prov = extract_open_library_isbn(ol_isbn)
            _apply_fields(sd, fields, prov)

        # 1b. Open Library /api/books
        ol_books = fetch_open_library_books(norm_isbn)
        if ol_books:
            fields, prov = extract_open_library_books(norm_isbn, ol_books)
            _apply_fields(sd, fields, prov)

        # 1c. Google Books
        gb = fetch_google_books(norm_isbn)
        if gb:
            fields, prov = extract_google_books(gb)
            _apply_fields(sd, fields, prov)

    elif title:
        # 2. 标题/作者回退
        sd.set_field("title", title, "user")
        if author:
            sd.set_field("authors", [author], "user")

        # 2a. Open Library 搜索
        ol_search = fetch_open_library_search(title, author)
        if ol_search:
            fields, prov = extract_open_library_search(ol_search)
            _apply_fields(sd, fields, prov)

        # 2b. Google Books 搜索
        gb_search = fetch_google_books_search(title, author)
        if gb_search:
            fields, prov = extract_google_books_search(gb_search)
            _apply_fields(sd, fields, prov)

        # 如果从搜索中发现了 ISBN，尝试更丰富的 ISBN 端点
        discovered_isbn = sd.data.get("isbn")
        if discovered_isbn:
            sd.set_field("isbn", _normalise_bookid(str(discovered_isbn)), "search_fallback", overwrite=True)
            deep_isbn = _normalise_bookid(str(discovered_isbn))
            ol_isbn2 = fetch_open_library_isbn(deep_isbn)
            if ol_isbn2:
                fields, prov = extract_open_library_isbn(ol_isbn2)
                _apply_fields(sd, fields, prov)
            gb2 = fetch_google_books(deep_isbn)
            if gb2:
                fields, prov = extract_google_books(gb2)
                _apply_fields(sd, fields, prov)
    else:
        sys.stderr.write(
            "[enrich] 错误: 请提供 --isbn，或同时提供 --title 和 --author。\n"
        )
        return 2

    # ------------------------------------------------------------------
    # 3. AI 合并（增强功能）
    # ------------------------------------------------------------------
    merged = ai_merge_validate(sd)
    if merged is not None:
        sd = merged
        sys.stderr.write("[enrich] 已应用 AI 多源合并。\n")

    # ------------------------------------------------------------------
    # 4. 输出
    # ------------------------------------------------------------------
    if output_mode == "calibre":
        target_isbn = norm_isbn or sd.data.get("isbn") or ""
        if not target_isbn:
            sys.stderr.write(
                "[enrich] 错误: 没有 ISBN 无法推送到 Calibre。\n"
            )
            return 1
        return push_to_calibre(sd, target_isbn)
    else:
        sys.stdout.write(sd.as_output(format))
        return 0


def _normalise_bookid(raw: str) -> str:
    """与 _normalise_isbn 相同，但也可处理其他图书标识符，
    返回清理后的结果。"""
    return _normalise_isbn(raw)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="基于 ISBN 的图书元数据充实工具。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python enrich.py --isbn 9787544270878
  python enrich.py --isbn 9787544270878 --format text
  python enrich.py --title "The Great Gatsby" --author "Fitzgerald"
  python enrich.py --isbn 9787544270878 --output calibre

环境变量:
  NEW_API_URL    AI 合并/验证端点（可选）
  NEW_API_KEY    AI 端点的 Bearer 令牌（可选）
        """.strip(),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--isbn", metavar="ISBN",
        help="图书的 ISBN-10 或 ISBN-13。",
    )
    group.add_argument(
        "--title", metavar="TITLE",
        help="图书标题（需要配合 --author 进行标题搜索）。",
    )
    parser.add_argument(
        "--author", metavar="AUTHOR",
        help="图书作者（使用 --title 时必需）。",
    )
    parser.add_argument(
        "--output", choices=["stdout", "calibre"], default="stdout",
        help="结果输出位置: 'stdout'（默认）或 'calibre'。",
    )
    parser.add_argument(
        "--format", choices=["json", "text"], default="json",
        help="输出格式: 'json'（默认）或 'text'（可读文本）。",
    )

    args = parser.parse_args(argv)

    # Validate --title + --author combination
    if args.title and not args.author:
        parser.error("使用 --title 时必须提供 --author。")

    exit_code = enrich(
        isbn=args.isbn,
        title=args.title,
        author=args.author,
        output_mode=args.output,
        format=args.format,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
