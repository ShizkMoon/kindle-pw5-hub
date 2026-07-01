#!/usr/bin/env python3
"""
KOReader 摘录同步工具。

解析 KOReader JSON 摘录文件，并将其转换为适合 Obsidian、
通用 JSON 流水线或纯文本阅读的结构化格式。

用法:
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

# KOReader SDR 目录中的标准元数据文件名
METADATA_FILENAMES = (
    "metadata.lua",
    "metadata.json",
    "settings.reader.lua",
)

# 文件名模式: Author - Title_sdr（常见的 KOReader SDR 命名）
_SDR_DIR_RE = re.compile(
    r"^(?P<author>.+?)\s*[-–—]\s*(?P<title>.+?)(?:_sdr)?$",
    re.IGNORECASE,
)

USER_AGENT = "koreader-sync/1.0 (highlight-tool)"


# ---------------------------------------------------------------------------
# WebDAV helpers
# ---------------------------------------------------------------------------

def _parse_webdav_url(url: str) -> Tuple[str, str, str, str]:
    """将 ``webdav://user:pass@host/path`` URL 解析为各组成部分。

    返回 ``(base_url, user, password, directory_path)``。
    """
    # webdav://user:pass@host:port/path  -- 去除协议前缀
    rest = url[len("webdav://"):]
    # 将认证信息与主机+路径分离
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
    # 提取第一个 / 之后的路径部分
    parts = hostpath.split("/", 1)
    if len(parts) == 2:
        directory_path = "/" + parts[1].rstrip("/") + "/"

    return base, user, password, directory_path


def _webdav_list(base: str, user: str, password: str, path: str) -> List[str]:
    """对 WebDAV 服务器上的 *path* 执行 PROPFIND，返回 href 列表。"""
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
            f"[sync] WebDAV PROPFIND 失败 (HTTP {exc.code})，路径: {path}\n"
        )
        return []
    except (urllib.error.URLError, OSError) as exc:
        sys.stderr.write(f"[sync] WebDAV 连接错误: {exc}\n")
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
    """从 WebDAV GET 单个文件。返回原始字节或 *None*。"""
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
            f"[sync] 获取 WebDAV 路径 {path} 失败: {exc}\n"
        )
        return None


def _is_webdav(source: str) -> bool:
    return source.startswith("webdav://")


# ---------------------------------------------------------------------------
# KOReader SDR 元数据提取
# ---------------------------------------------------------------------------

def _extract_sdr_metadata(
    sdr_dir: str,
) -> Dict[str, str]:
    """尝试从 KOReader SDR 目录读取元数据。

    查找 ``metadata.lua``（简单的逐行解析）或
    ``metadata.json``。
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
            # 简单的 Lua 键值: key = "value" 或 key = [[value]]
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
    """从源路径中启发式提取标题/作者。

    如果源是一个名为 ``Author - Title_sdr`` 的目录，
    则进行解析。
    """
    meta: Dict[str, str] = {}
    if _is_webdav(source):
        # 尝试从 URL 路径猜测
        path_part = urllib.parse.urlparse(source.replace("webdav://", "http://")).path
        dirname = os.path.basename(path_part.rstrip("/"))
    else:
        dirname = os.path.basename(source.rstrip(os.sep))
        # 如果源是文件，使用其父目录名
        if os.path.isfile(source):
            dirname = os.path.basename(os.path.dirname(source))

    match = _SDR_DIR_RE.match(dirname)
    if match:
        meta["author"] = match.group("author").strip()
        meta["title"] = match.group("title").strip()
    return meta


# ---------------------------------------------------------------------------
# 摘录解析与去重
# ---------------------------------------------------------------------------

def parse_highlights(raw_json: str) -> List[Dict[str, Any]]:
    """将 KOReader 摘录 JSON 字符串解析为字典列表。

    预期格式：一个 JSON 数组，每个条目包含 ``text``、
    ``chapter``、``datetime``（或 ``timestamp``）、``note``、
    ``page`` 等键。
    """
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"[sync] 无效的 JSON: {exc}\n")
        return []

    if not isinstance(data, list):
        # 有时 KOReader 将摘录包装在按页码索引的对象中
        if isinstance(data, dict):
            data = data.get("highlight", data.get("highlights", []))
            if not isinstance(data, list):
                sys.stderr.write(
                    "[sync] 意外的 JSON 结构；预期为列表。\n"
                )
                return []

    results: List[Dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if not entry.get("text"):
            continue  # 跳过没有摘录文本的条目

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
    """移除 ``text`` 和 ``chapter`` 完全相同的重复摘录条目。"""
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
    """按 ``chapter`` 字段对摘录进行分组。

    没有章节的摘录归入键 ``(未标注)``。
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for h in highlights:
        ch = h["chapter"].strip() or "(未标注)"
        groups.setdefault(ch, []).append(h)
    return groups


# ---------------------------------------------------------------------------
# 输出格式化
# ---------------------------------------------------------------------------

def _make_yaml_frontmatter(
    meta: Dict[str, str], highlight_count: int
) -> str:
    """构建兼容 Obsidian 的 YAML frontmatter 字符串。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "---",
        f'title: "{meta.get("title", "未命名")}"',
        f"author: {meta.get('author', '未知')}",
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
    """将摘录渲染为兼容 Obsidian 的 markdown。"""
    groups = group_by_chapter(highlights)
    parts = [_make_yaml_frontmatter(meta, len(highlights))]

    title = meta.get("title", "未命名")
    parts.append(f"# {title} — 摘录")
    parts.append("")

    for chapter, items in groups.items():
        parts.append(f"## {chapter}")
        parts.append("")
        for h in items:
            parts.append(f"> {h['text']}")
            if h.get("note"):
                parts.append(f"  — *笔记:* {h['note']}")
            if h.get("page"):
                parts.append(f"  — 页码 {h['page']}")
            parts.append("")
    return "\n".join(parts)


def format_json_output(
    highlights: List[Dict[str, Any]],
    meta: Dict[str, str],
) -> str:
    """将摘录渲染为整洁的 JSON 文档。"""
    groups = group_by_chapter(highlights)
    output: Dict[str, Any] = {
        "meta": {
            "title": meta.get("title", "未命名"),
            "author": meta.get("author", "未知"),
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
    """将摘录渲染为按章节分组的纯文本。"""
    groups = group_by_chapter(highlights)
    lines: List[str] = []
    title = meta.get("title", "未命名")
    author = meta.get("author", "未知")
    lines.append(f"{title}")
    if author:
        lines.append(f"作者：{author}")
    lines.append(f"{len(highlights)} 条摘录")
    lines.append("=" * 60)
    lines.append("")

    for chapter, items in groups.items():
        lines.append(f"--- {chapter} ---")
        lines.append("")
        for h in items:
            lines.append(f"  * {h['text']}")
            if h.get("note"):
                lines.append(f"    [笔记: {h['note']}]")
            if h.get("page"):
                lines.append(f"    [页码: {h['page']}]")
            lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 源加载
# ---------------------------------------------------------------------------

def load_highlights(source: str) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """从 *source*（本地路径或 webdav URL）加载摘录。

    返回 ``(highlights, metadata_dict)``。
    """
    meta: Dict[str, str] = _guess_metadata_from_path(source)

    if _is_webdav(source):
        base, user, password, dirpath = _parse_webdav_url(source)
        # 列出文件，查找 JSON 摘录文件
        hrefs = _webdav_list(base, user, password, dirpath)
        all_highlights: List[Dict[str, Any]] = []
        for href in hrefs:
            if not href.lower().endswith(".json"):
                continue
            raw = _webdav_fetch(base, user, password, href)
            if raw is None:
                continue
            all_highlights.extend(parse_highlights(raw.decode("utf-8", errors="replace")))

        # 也尝试从远程 SDR 目录读取元数据
        for meta_file in METADATA_FILENAMES:
            raw = _webdav_fetch(base, user, password, dirpath + meta_file)
            if raw is not None:
                meta.update(_extract_remote_metadata(raw, meta_file))
        return deduplicate(all_highlights), meta

    # --- 本地路径 ---
    if os.path.isdir(source):
        # SDR 目录：读取主要的 JSON 摘录文件
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
                sys.stderr.write(f"[sync] 无法读取 {fpath}: {exc}\n")

        # 也检查父目录的 SDR 命名
        parent_meta = _guess_metadata_from_path(source)
        for k, v in parent_meta.items():
            meta.setdefault(k, v)

        return deduplicate(all_highlights), meta

    # 单个文件
    try:
        with open(source, "r", encoding="utf-8", errors="replace") as fh:
            highlights = parse_highlights(fh.read())
    except OSError as exc:
        sys.stderr.write(f"[sync] 无法读取 {source}: {exc}\n")
        return [], meta

    # 尝试从父 SDR 目录读取元数据
    parent = os.path.dirname(source)
    if os.path.isdir(parent):
        sdr_meta = _extract_sdr_metadata(parent)
        meta.update(sdr_meta)
    parent_meta = _guess_metadata_from_path(source)
    for k, v in parent_meta.items():
        meta.setdefault(k, v)

    return deduplicate(highlights), meta


def _extract_remote_metadata(raw: bytes, filename: str) -> Dict[str, str]:
    """从远程获取的元数据文件字节中提取元数据。"""
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
# 主流程编排
# ---------------------------------------------------------------------------

def sync_highlights(
    source: str,
    output_format: str = "json",
    output_dir: Optional[str] = None,
) -> int:
    """加载、处理并输出摘录。

    成功返回 0，失败返回非零。
    """
    highlights, meta = load_highlights(source)

    if not highlights:
        sys.stderr.write("[sync] 未找到摘录。\n")
        return 1

    meta.setdefault("book_filename", os.path.basename(source.rstrip("/\\")))

    # 渲染
    formatters: Dict[str, Callable[[List[Dict[str, Any]], Dict[str, str]], str]] = {
        "json": format_json_output,
        "markdown": format_markdown,
        "text": format_text,
    }
    formatter = formatters.get(output_format, format_json_output)
    output_text = formatter(highlights, meta)

    # 扩展名映射
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
            sys.stderr.write(f"[sync] 已写入: {out_path}\n")
        except OSError as exc:
            sys.stderr.write(f"[sync] 无法写入 {out_path}: {exc}\n")
            return 1
    else:
        sys.stdout.write(output_text)

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="KOReader 摘录同步工具。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
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
            "KOReader 摘录 JSON 文件、SDR 目录或指向"
            "远程摘录目录的 webdav:// URL 的路径。"
        ),
    )
    parser.add_argument(
        "--output", choices=["json", "markdown", "text"], default="json",
        help="输出格式。'markdown' 包含 Obsidian YAML frontmatter。",
    )
    parser.add_argument(
        "--output-dir", metavar="DIR",
        help=(
            "输出文件写入的目录。"
            "如果省略，输出打印到 stdout。"
        ),
    )
    parser.add_argument(
        "--watch", type=int, default=0, metavar="SECONDS",
        help=(
            "每隔 N 秒轮询源以获取新摘录。"
            "适用于持续同步。"
        ),
    )

    args = parser.parse_args(argv)

    if args.watch > 0:
        sys.stderr.write(
            f"[sync] 正在监视 {args.source}，间隔 {args.watch} 秒。"
            "按 Ctrl+C 停止。\n"
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
                        f"[sync] 同步返回退出码 {exit_code}。"
                        "将在下次轮询时重试。\n"
                    )
                time.sleep(args.watch)
        except KeyboardInterrupt:
            sys.stderr.write("\n[sync] 监视已停止。\n")
            sys.exit(0)
    else:
        sys.exit(sync_highlights(
            args.source,
            output_format=args.output,
            output_dir=args.output_dir,
        ))


if __name__ == "__main__":
    main()
