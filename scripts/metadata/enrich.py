#!/usr/bin/env python3
"""
ISBN-based metadata enrichment tool.

Fetches book metadata from free public APIs (Open Library, Google Books)
and outputs structured JSON or human-readable text. Can optionally push
metadata directly into a Calibre library via calibredb.

Usage:
    python enrich.py --isbn 9787544270878
    python enrich.py --isbn 9787544270878 --format text
    python enrich.py --title "Book Title" --author "Author Name"
    python enrich.py --isbn 9787544270878 --output calibre
    python enrich.py --isbn 9787544270878 --output calibre --format json

Environment variables (optional / bonus):
    NEW_API_URL  - URL of an AI-based merge/validation endpoint
    NEW_API_KEY  - Bearer token for the AI endpoint
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
# Helpers
# ---------------------------------------------------------------------------

def _normalise_isbn(raw: str) -> str:
    """Strip hyphens, spaces, and 'ISBN' prefix; return the raw digits."""
    s = raw.strip().upper()
    s = re.sub(r"^ISBN(?:-1[03])?:?\s*", "", s, flags=re.IGNORECASE)
    s = s.replace("-", "").replace(" ", "")
    return s


def _fetch_json(url: str) -> Optional[Any]:
    """GET *url*, parse JSON, with retry + exponential backoff on 429/5xx."""
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
                    f"[enrich] HTTP {exc.code} – retrying in {wait:.1f}s "
                    f"(attempt {attempt}/{MAX_RETRIES})\n"
                )
                time.sleep(wait)
                continue
            sys.stderr.write(f"[enrich] HTTP {exc.code} for {url}\n")
            return None
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            sys.stderr.write(f"[enrich] Request failed: {exc}\n")
            return None
    sys.stderr.write(f"[enrich] Exhausted retries for {url}\n")
    return None


# ---------------------------------------------------------------------------
# API-sourcing context manager – records which API each field came from
# ---------------------------------------------------------------------------

class SourcedData:
    """Holds the final structured metadata plus per-field provenance."""

    def __init__(self) -> None:
        self.data: Dict[str, Any] = {}
        self.sources: Dict[str, str] = {}

    def set_field(
        self, key: str, value: Any, source: str, *, overwrite: bool = False
    ) -> None:
        """Store *value* under *key* and record its *source*.

        By default, existing values are not overwritten (the first source
        wins).  Pass *overwrite=True* to force an update.
        """
        if key in self.data and not overwrite:
            return
        self.data[key] = value
        self.sources[key] = source

    def as_output(self, format: str = "json") -> str:
        """Render the metadata as JSON or as human-readable text."""
        if format == "json":
            result: Dict[str, Any] = {
                "metadata": self.data,
                "sources": self.sources,
            }
            return json.dumps(result, ensure_ascii=False, indent=2)
        # -- text / human-readable
        lines: List[str] = []
        for key, val in self.data.items():
            src = self.sources.get(key, "unknown")
            if isinstance(val, list):
                lines.append(f"{key}:")
                for item in val:
                    lines.append(f"  - {item}")
            else:
                lines.append(f"{key}: {val}")
            lines.append(f"  ^-- source: {src}")
            lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_open_library_isbn(isbn: str) -> Optional[Dict[str, Any]]:
    """Fetch the Open Library /isbn/{isbn}.json endpoint."""
    url = OPEN_LIBRARY_ISBN_URL.format(isbn=isbn)
    return _fetch_json(url)


def fetch_open_library_books(isbn: str) -> Optional[Dict[str, Any]]:
    """Fetch the Open Library /api/books endpoint (richer data)."""
    url = OPEN_LIBRARY_BOOKS_URL.format(isbn=isbn)
    return _fetch_json(url)


def fetch_google_books(isbn: str) -> Optional[Dict[str, Any]]:
    """Fetch the Google Books API volumes endpoint."""
    url = GOOGLE_BOOKS_URL.format(isbn=isbn)
    return _fetch_json(url)


def fetch_open_library_search(
    title: str, author: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Fallback search via Open Library's search API when ISBN is unavailable."""
    q = f"title:{title}"
    if author:
        q += f" author:{author}"
    params = urllib.parse.urlencode({"q": q, "limit": 3})
    url = f"https://openlibrary.org/search.json?{params}"
    return _fetch_json(url)


def fetch_google_books_search(
    title: str, author: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Fallback search via Google Books when ISBN is unavailable."""
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
    """Extract fields from the /isbn/{isbn}.json payload."""
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
    """Extract fields from the /api/books payload."""
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
    """Extract fields from the Google Books API volumes payload."""
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
    """Extract fields from Open Library's /search.json."""
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
    """Extract fields from Google Books search results."""
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
    """Copy keys from *source* dict to *target* dict using *mapping*,
    and record provenance.

    *mapping* is {source_key: target_key}.
    """
    for sk, tk in mapping.items():
        if sk in source and source[sk] is not None:
            target[tk] = source[sk]
            prov.append((tk, src_name))


def _apply_fields(sd: SourcedData, fields: Dict[str, Any], prov: List[Tuple[str, str]]) -> None:
    """Populate the SourcedData container from extracted fields and provenance."""
    for key, value in fields.items():
        sd.set_field(key, value, "unknown")
    for key, src in prov:
        sd.sources[key] = src


# ---------------------------------------------------------------------------
# AI merge (bonus)
# ---------------------------------------------------------------------------

def ai_merge_validate(sd: SourcedData) -> Optional[SourcedData]:
    """If NEW_API_URL + NEW_API_KEY are set, POST the current metadata to an AI
    endpoint that returns validated / merged data.

    The endpoint is expected to accept JSON like:
        {"metadata": ..., "sources": ...}
    and return:
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
        sys.stderr.write(f"[enrich] AI merge call failed: {exc}\n")
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
    """Find the book in the Calibre library by ISBN and update its metadata
    via the ``calibredb`` CLI.

    Returns 0 on success, non-zero on failure.
    """
    # 1) Locate the book
    try:
        result = subprocess.run(
            ["calibredb", "search", f"isbn:{isbn}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        sys.stderr.write(
            "[enrich] ERROR: calibredb not found. Is Calibre installed "
            "and on PATH?\n"
        )
        return 1
    except subprocess.TimeoutExpired:
        sys.stderr.write("[enrich] ERROR: calibredb search timed out.\n")
        return 1

    if result.returncode != 0 or not result.stdout.strip():
        sys.stderr.write(
            f"[enrich] No Calibre book found with ISBN {isbn}. "
            f"Add the book to Calibre first.\n"
        )
        return 1

    book_ids = result.stdout.strip().splitlines()
    if len(book_ids) > 1:
        sys.stderr.write(
            f"[enrich] Multiple books match ISBN {isbn}, using first: "
            f"{book_ids[0]}\n"
        )
    book_id = book_ids[0].strip()

    # 2) Build set-metadata args
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
        sys.stderr.write("[enrich] No metadata fields to push to Calibre.\n")
        return 0

    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        sys.stderr.write("[enrich] ERROR: calibredb set_metadata timed out.\n")
        return 1

    if proc.returncode != 0:
        sys.stderr.write(
            f"[enrich] calibredb error: {proc.stderr or proc.stdout}\n"
        )
        return proc.returncode

    sys.stderr.write(
        f"[enrich] Successfully updated Calibre metadata for book {book_id}.\n"
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
    """Run the full enrichment pipeline.

    Returns 0 on success, non-zero on failure.
    """
    sd = SourcedData()
    norm_isbn = _normalise_bookid(isbn) if isbn else None

    # ------------------------------------------------------------------
    # 1. ISBN-based lookup
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
        # 2. Title / author fallback
        sd.set_field("title", title, "user")
        if author:
            sd.set_field("authors", [author], "user")

        # 2a. Open Library search
        ol_search = fetch_open_library_search(title, author)
        if ol_search:
            fields, prov = extract_open_library_search(ol_search)
            _apply_fields(sd, fields, prov)

        # 2b. Google Books search
        gb_search = fetch_google_books_search(title, author)
        if gb_search:
            fields, prov = extract_google_books_search(gb_search)
            _apply_fields(sd, fields, prov)

        # If we discovered an ISBN from search, try the richer ISBN endpoints
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
            "[enrich] ERROR: Provide --isbn or both --title and --author.\n"
        )
        return 2

    # ------------------------------------------------------------------
    # 3. AI merge (bonus)
    # ------------------------------------------------------------------
    merged = ai_merge_validate(sd)
    if merged is not None:
        sd = merged
        sys.stderr.write("[enrich] Applied AI multi-source merge.\n")

    # ------------------------------------------------------------------
    # 4. Output
    # ------------------------------------------------------------------
    if output_mode == "calibre":
        target_isbn = norm_isbn or sd.data.get("isbn") or ""
        if not target_isbn:
            sys.stderr.write(
                "[enrich] ERROR: Cannot push to Calibre without an ISBN.\n"
            )
            return 1
        return push_to_calibre(sd, target_isbn)
    else:
        sys.stdout.write(sd.as_output(format))
        return 0


def _normalise_bookid(raw: str) -> str:
    """Same as _normalise_isbn but also handles other book identifiers by
    returning them cleaned."""
    return _normalise_isbn(raw)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="ISBN-based book metadata enrichment tool.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python enrich.py --isbn 9787544270878
  python enrich.py --isbn 9787544270878 --format text
  python enrich.py --title "The Great Gatsby" --author "Fitzgerald"
  python enrich.py --isbn 9787544270878 --output calibre

Environment variables:
  NEW_API_URL    AI merge/validation endpoint (optional)
  NEW_API_KEY    Bearer token for the AI endpoint (optional)
        """.strip(),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--isbn", metavar="ISBN",
        help="ISBN-10 or ISBN-13 of the book.",
    )
    group.add_argument(
        "--title", metavar="TITLE",
        help="Book title (requires --author for title-based search).",
    )
    parser.add_argument(
        "--author", metavar="AUTHOR",
        help="Book author (required when using --title).",
    )
    parser.add_argument(
        "--output", choices=["stdout", "calibre"], default="stdout",
        help="Where to send results: 'stdout' (default) or 'calibre'.",
    )
    parser.add_argument(
        "--format", choices=["json", "text"], default="json",
        help="Output format: 'json' (default) or 'text' (human-readable).",
    )

    args = parser.parse_args(argv)

    # Validate --title + --author combination
    if args.title and not args.author:
        parser.error("--author is required when using --title.")

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
