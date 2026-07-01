#!/usr/bin/env python3
"""
EPUB validator wrapper for EPUBCheck.

Wraps the EPUBCheck Java tool to validate EPUB files and presents
a clean summary of the results.

Usage:
    python validate.py book.epub
    python validate.py book.epub --quiet
    python validate.py book.epub --epubcheck-jar /path/to/epubcheck.jar

Requires:
    - Java Runtime Environment (JRE 8+)
    - epubcheck.jar (auto-detected or specified via --epubcheck-jar)
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
    """Return the path to the java executable, or None if not found."""
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
    Search for epubcheck.jar in well-known locations.

    Order of precedence:
      1. Same directory as this script
      2. Current working directory
      3. Every directory on PATH
      4. Common platform locations
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
    """Extract the primary location from an EPUBCheck message dict."""
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
    Parse EPUBCheck JSON output.

    Returns
    -------
    tuple[list[dict], list[dict], list[dict]]
        (errors, warnings, infos) -- each entry is a dict with keys
        id, message, suggestion, file, line, column.
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
    """Build a human-readable location string from an issue entry."""
    parts: list[str] = []
    if entry["file"]:
        parts.append(str(entry["file"]))
    if entry["line"]:
        loc = f"line {entry['line']}"
        if entry["column"]:
            loc += f", col {entry['column']}"
        parts.append(loc)
    return " @ ".join(parts) if parts else "(no location)"


def print_issue(entry: dict, label: str) -> None:
    """Print a single validated issue to stdout."""
    loc_str = _format_location(entry)
    print(f"  [{label}] {entry['id']}: {entry['message']}")
    print(f"          {loc_str}")
    if entry.get("suggestion"):
        print(f"          Hint: {entry['suggestion']}")


def print_summary(epub_path: str, errors: list, warnings: list,
                  infos: list, quiet: bool) -> None:
    """Print the full validation summary."""
    epub_name = os.path.basename(epub_path)
    total = len(errors) + len(warnings) + len(infos)

    print(f"EPUBCheck Results for: {epub_name}")
    print("=" * 60)
    print(f"  Errors:   {len(errors)}")
    print(f"  Warnings: {len(warnings)}")
    print(f"  Info:     {len(infos)}")
    print(f"  Total:    {total}")
    print()

    if total == 0:
        print("No issues found -- EPUB is valid.")
        return

    # Errors are always printed
    if errors:
        print("-" * 60)
        print(f"ERRORS ({len(errors)}):")
        print()
        for entry in errors:
            print_issue(entry, "ERROR")
        print()

    if quiet:
        return

    if warnings:
        print("-" * 60)
        print(f"WARNINGS ({len(warnings)}):")
        print()
        for entry in warnings:
            print_issue(entry, "WARNING")
        print()

    if infos:
        print("-" * 60)
        print(f"INFO ({len(infos)}):")
        print()
        for entry in infos:
            print_issue(entry, "INFO")
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Validate EPUB files using EPUBCheck.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python validate.py book.epub
  python validate.py book.epub --quiet
  python validate.py book.epub --epubcheck-jar /opt/epubcheck/epubcheck.jar
        """,
    )
    parser.add_argument(
        "epub",
        help="Path to the EPUB file to validate",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Only print errors (suppress warnings and info messages)",
    )
    parser.add_argument(
        "--epubcheck-jar",
        dest="epubcheck_jar",
        default=None,
        help="Path to epubcheck.jar (overrides auto-detection)",
    )
    args = parser.parse_args(argv)

    # --- sanity checks --------------------------------------------------
    if not os.path.isfile(args.epub):
        print(f"Error: EPUB file not found: {args.epub}", file=sys.stderr)
        sys.exit(2)

    java_path = find_java()
    if not java_path:
        print("Error: Java not found.", file=sys.stderr)
        print("", file=sys.stderr)
        print("EPUBCheck requires a Java Runtime Environment (JRE 8 or later).", file=sys.stderr)
        print("Install Java from https://adoptium.net/ or your system package manager.", file=sys.stderr)
        sys.exit(2)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    if args.epubcheck_jar:
        jar_path = args.epubcheck_jar
        if not os.path.isfile(jar_path):
            print(f"Error: epubcheck.jar not found at: {jar_path}", file=sys.stderr)
            sys.exit(2)
    else:
        jar_path = find_epubcheck_jar(script_dir)
        if not jar_path:
            print("Error: epubcheck.jar not found.", file=sys.stderr)
            print(file=sys.stderr)
            print("EPUBCheck is required to validate EPUB files.", file=sys.stderr)
            print("Download it from: https://github.com/w3c/epubcheck/releases", file=sys.stderr)
            print(file=sys.stderr)
            print("Place epubcheck.jar in one of these locations:", file=sys.stderr)
            print(f"  * This script's directory: {script_dir}", file=sys.stderr)
            print("  * Current working directory", file=sys.stderr)
            print("  * Any directory in your PATH", file=sys.stderr)
            print("  * Or use --epubcheck-jar to specify the path directly", file=sys.stderr)
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
        print("Error: EPUBCheck timed out after 300 seconds.", file=sys.stderr)
        sys.exit(2)
    except FileNotFoundError:
        print("Error: Java executable not found at runtime.", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(f"Error: Failed to run EPUBCheck: {exc}", file=sys.stderr)
        sys.exit(2)

    # If epubcheck itself returned non-zero it still produced JSON on stdout
    # in many cases, so we try to parse first.

    raw_output = result.stdout.strip()

    if not raw_output:
        # epubcheck sometimes writes errors to stderr and nothing to stdout.
        if result.stderr.strip():
            print("Error: EPUBCheck produced no parseable output.", file=sys.stderr)
            print(file=sys.stderr)
            print("stderr:", file=sys.stderr)
            print(result.stderr.strip(), file=sys.stderr)
        else:
            print("Error: EPUBCheck produced no output.", file=sys.stderr)
        sys.exit(2)

    # --- parse output ---------------------------------------------------
    try:
        errors, warnings, infos = parse_epubcheck_output(raw_output)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Error: Failed to parse EPUBCheck JSON output: {exc}", file=sys.stderr)
        print(file=sys.stderr)
        print("Raw output received:", file=sys.stderr)
        # Print first 3000 characters to avoid overwhelming the terminal
        print(raw_output[:3000], file=sys.stderr)
        if result.stderr.strip():
            print(file=sys.stderr)
            print("stderr:", file=sys.stderr)
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
