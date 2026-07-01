#!/usr/bin/env python3
"""
EPUBCheck 的 EPUB 验证器封装。

封装 EPUBCheck Java 工具以验证 EPUB 文件，并以清晰的摘要形式呈现验证结果。

用法：
    python validate.py book.epub
    python validate.py book.epub --quiet
    python validate.py book.epub --epubcheck-jar /path/to/epubcheck.jar

依赖：
    - Java 运行环境（JRE 8 或更高版本）
    - epubcheck.jar（自动检测，或通过 --epubcheck-jar 指定）
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Locating epubcheck.jar
# ---------------------------------------------------------------------------

def find_java() -> str | None:
    """返回 Java 可执行文件的路径，若未找到则返回 None。"""
    java = shutil.which("java")
    if java:
        return java
    # Windows: check JAVA_HOME
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = os.path.join(java_home, "bin", "java.exe")
        if os.path.isfile(candidate):
            return candidate
        candidate = os.path.join(java_home, "bin", "java")
        if os.path.isfile(candidate):
            return candidate
    return None


def find_epubcheck_jar(script_dir: str) -> str | None:
    """
    在常用位置搜索 epubcheck.jar。

    查找优先级：
      1. 本脚本所在目录
      2. 当前工作目录
      3. PATH 中的每个目录
      4. 各平台的常见路径
    """
    candidates: list[str] = []

    # 1 -- script directory
    candidates.append(os.path.join(script_dir, "epubcheck.jar"))

    # 2 -- current working directory
    candidates.append(os.path.join(os.getcwd(), "epubcheck.jar"))

    # 3 -- PATH
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        if path_dir:
            candidates.append(os.path.join(path_dir, "epubcheck.jar"))

    # 4 -- well-known locations
    candidates.extend([
        os.path.expanduser("~/epubcheck.jar"),
        "/usr/local/bin/epubcheck.jar",
        "/usr/share/java/epubcheck.jar",
        "/opt/epubcheck/epubcheck.jar",
    ])

    # Also try finding any epubcheck*.jar (some distros rename it)
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    # Fallback: glob for epubcheck*.jar in script dir
    try:
        for entry in os.listdir(script_dir):
            if entry.endswith(".jar") and "epubcheck" in entry.lower():
                full = os.path.join(script_dir, entry)
                if os.path.isfile(full):
                    return full
    except OSError:
        pass

    return None


# ---------------------------------------------------------------------------
# Parsing EPUBCheck JSON output
# ---------------------------------------------------------------------------

def _safe_location(msg: dict) -> dict[str, object]:
    """从 EPUBCheck 消息字典中提取主要位置信息。"""
    locations = msg.get("locations") or []
    if locations:
        loc = locations[0]
        return {
            "file": loc.get("path", ""),
            "line": loc.get("line", 0),
            "column": loc.get("column", 0),
        }
    return {"file": "", "line": 0, "column": 0}


def parse_epubcheck_output(raw_json: str):
    """
    解析 EPUBCheck 的 JSON 输出。

    返回值
    -------
    tuple[list[dict], list[dict], list[dict]]
        (错误, 警告, 信息) —— 每项为一个字典，包含以下键：
        id, message, suggestion, file, line, column。
    """
    data = json.loads(raw_json)

    # EPUBCheck may wrap messages inside a top-level key.  Handle both the
    # raw-messages-array format and the {"messages": [...]} format.
    if isinstance(data, list):
        messages = data
    elif isinstance(data, dict):
        messages = data.get("messages", [])
    else:
        raise ValueError(f"Unexpected EPUBCheck output type: {type(data)}")

    errors: list[dict] = []
    warnings: list[dict] = []
    infos:   list[dict] = []

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        severity = str(msg.get("severity", "")).upper()
        loc = _safe_location(msg)

        entry = {
            "id":         msg.get("ID", ""),
            "message":    msg.get("message", ""),
            "suggestion": msg.get("suggestion", ""),
            "file":       loc["file"],
            "line":       loc["line"],
            "column":     loc["column"],
        }

        if severity in ("ERROR", "FATAL", "SEVERE"):
            errors.append(entry)
        elif severity == "WARNING":
            warnings.append(entry)
        else:
            infos.append(entry)

    return errors, warnings, infos


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _format_location(entry: dict) -> str:
    """根据问题条目构建可读的位置字符串。"""
    parts: list[str] = []
    if entry["file"]:
        parts.append(str(entry["file"]))
    if entry["line"]:
        loc = f"第 {entry['line']} 行"
        if entry["column"]:
            loc += f"，第 {entry['column']} 列"
        parts.append(loc)
    return " / ".join(parts) if parts else "（无位置信息）"


def print_issue(entry: dict, label: str) -> None:
    """向标准输出打印一条验证问题。"""
    loc_str = _format_location(entry)
    print(f"  [{label}] {entry['id']}：{entry['message']}")
    print(f"          {loc_str}")
    if entry.get("suggestion"):
        print(f"          提示：{entry['suggestion']}")


def print_summary(epub_path: str, errors: list, warnings: list,
                  infos: list, quiet: bool) -> None:
    """打印完整的验证摘要。"""
    epub_name = os.path.basename(epub_path)
    total = len(errors) + len(warnings) + len(infos)

    print(f"EPUBCheck 验证结果：{epub_name}")
    print("=" * 60)
    print(f"  错误：  {len(errors)}")
    print(f"  警告：  {len(warnings)}")
    print(f"  信息：  {len(infos)}")
    print(f"  合计：  {total}")
    print()

    if total == 0:
        print("未发现问题 —— EPUB 验证通过。")
        return

    # Errors are always printed
    if errors:
        print("-" * 60)
        print(f"错误（{len(errors)}）：")
        print()
        for entry in errors:
            print_issue(entry, "错误")
        print()

    if quiet:
        return

    if warnings:
        print("-" * 60)
        print(f"警告（{len(warnings)}）：")
        print()
        for entry in warnings:
            print_issue(entry, "警告")
        print()

    if infos:
        print("-" * 60)
        print(f"信息（{len(infos)}）：")
        print()
        for entry in infos:
            print_issue(entry, "信息")
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="使用 EPUBCheck 验证 EPUB 文件。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python validate.py book.epub
  python validate.py book.epub --quiet
  python validate.py book.epub --epubcheck-jar /opt/epubcheck/epubcheck.jar
        """,
    )
    parser.add_argument(
        "epub",
        help="要验证的 EPUB 文件路径",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="仅显示错误（隐藏警告和信息）",
    )
    parser.add_argument(
        "--epubcheck-jar",
        dest="epubcheck_jar",
        default=None,
        help="epubcheck.jar 的路径（覆盖自动检测）",
    )
    args = parser.parse_args(argv)

    # --- sanity checks --------------------------------------------------
    if not os.path.isfile(args.epub):
        print(f"错误：找不到 EPUB 文件：{args.epub}", file=sys.stderr)
        sys.exit(2)

    java_path = find_java()
    if not java_path:
        print("错误：未找到 Java。", file=sys.stderr)
        print("", file=sys.stderr)
        print("EPUBCheck 需要 Java 运行环境（JRE 8 或更高版本）。", file=sys.stderr)
        print("请从 https://adoptium.net/ 或系统包管理器安装 Java。", file=sys.stderr)
        sys.exit(2)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    if args.epubcheck_jar:
        jar_path = args.epubcheck_jar
        if not os.path.isfile(jar_path):
            print(f"错误：在以下路径找不到 epubcheck.jar：{jar_path}", file=sys.stderr)
            sys.exit(2)
    else:
        jar_path = find_epubcheck_jar(script_dir)
        if not jar_path:
            print("错误：找不到 epubcheck.jar。", file=sys.stderr)
            print(file=sys.stderr)
            print("验证 EPUB 文件需要 EPUBCheck。", file=sys.stderr)
            print("请从以下地址下载：https://github.com/w3c/epubcheck/releases", file=sys.stderr)
            print(file=sys.stderr)
            print("请将 epubcheck.jar 放在以下任意位置：", file=sys.stderr)
            print(f"  * 本脚本所在目录：{script_dir}", file=sys.stderr)
            print("  * 当前工作目录", file=sys.stderr)
            print("  * PATH 中的任意目录", file=sys.stderr)
            print("  * 或使用 --epubcheck-jar 直接指定路径", file=sys.stderr)
            sys.exit(2)

    # --- run EPUBCheck --------------------------------------------------
    epub_abs = os.path.abspath(args.epub)

    try:
        result = subprocess.run(
            [java_path, "-jar", jar_path, "--json", epub_abs],
            capture_output=True,
            text=True,
            timeout=300,  # generous timeout for large EPUBs
        )
    except subprocess.TimeoutExpired:
        print("错误：EPUBCheck 在 300 秒后超时。", file=sys.stderr)
        sys.exit(2)
    except FileNotFoundError:
        print("错误：运行时找不到 Java 可执行文件。", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(f"错误：运行 EPUBCheck 失败：{exc}", file=sys.stderr)
        sys.exit(2)

    # If epubcheck itself returned non-zero it still produced JSON on stdout
    # in many cases, so we try to parse first.

    raw_output = result.stdout.strip()

    if not raw_output:
        # epubcheck sometimes writes errors to stderr and nothing to stdout.
        if result.stderr.strip():
            print("错误：EPUBCheck 未产生可解析的输出。", file=sys.stderr)
            print(file=sys.stderr)
            print("stderr：", file=sys.stderr)
            print(result.stderr.strip(), file=sys.stderr)
        else:
            print("错误：EPUBCheck 未产生任何输出。", file=sys.stderr)
        sys.exit(2)

    # --- parse output ---------------------------------------------------
    try:
        errors, warnings, infos = parse_epubcheck_output(raw_output)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"错误：解析 EPUBCheck JSON 输出失败：{exc}", file=sys.stderr)
        print(file=sys.stderr)
        print("收到的原始输出：", file=sys.stderr)
        # Print first 3000 characters to avoid overwhelming the terminal
        print(raw_output[:3000], file=sys.stderr)
        if result.stderr.strip():
            print(file=sys.stderr)
            print("stderr：", file=sys.stderr)
            print(result.stderr.strip()[:2000], file=sys.stderr)
        sys.exit(2)

    # --- print results --------------------------------------------------
    print_summary(args.epub, errors, warnings, infos, args.quiet)

    if errors:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
