from __future__ import annotations

import json
import posixpath
import re
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from .config import TypographyConfig, TypographyMode
from .textdecode import decode_css, decode_markup


KOREADER_LITERARY_CSS = """
html, body {
  margin: 0;
  padding: 0;
}

body {
  line-height: 1.65;
  widows: 2;
  orphans: 2;
  text-align: justify;
  text-justify: inter-ideograph;
  overflow-wrap: anywhere;
  hanging-punctuation: allow-end;
}

p {
  margin: 0;
  text-indent: 2em;
  line-height: inherit;
}

p:empty {
  min-height: 1em;
}

h1, h2, h3, h4, h5, h6 {
  margin: 1.6em 0 1.1em;
  text-indent: 0;
  text-align: center;
  line-height: 1.35;
  break-after: avoid;
  page-break-after: avoid;
}

h1 { font-size: 1.6em; }
h2 { font-size: 1.4em; }
h3 { font-size: 1.2em; }

blockquote {
  margin: 1em 2em;
}

hr {
  width: 30%;
  margin: 1.6em auto;
  border: 0;
  border-top: 0.08em solid currentColor;
  opacity: 0.55;
}

figure {
  margin: 1em 0;
  text-align: center;
  break-inside: avoid;
  page-break-inside: avoid;
}

figcaption {
  margin-top: 0.5em;
  text-indent: 0;
  text-align: center;
  font-size: 0.9em;
}

img, svg {
  max-width: 100% !important;
  height: auto !important;
  object-fit: contain;
}

table {
  max-width: 100%;
  border-collapse: collapse;
}

pre, code {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

ruby rt {
  font-size: 0.55em;
}

font {
  font-size: inherit !important;
  font-family: inherit !important;
}
""".strip()


_NUMBER = r"(?:\d+(?:\.\d*)?|\.\d+)"
_ABSOLUTE_TYPOGRAPHY_RE = re.compile(
    rf"(?P<prefix>\b(?P<property>font-size|line-height)\s*:\s*)"
    rf"(?P<value>{_NUMBER})\s*(?P<unit>px|pt)\b",
    re.IGNORECASE,
)
_STYLE_BLOCK_RE = re.compile(r"(<style\b[^>]*>)(.*?)(</style\s*>)", re.IGNORECASE | re.DOTALL)
_DOUBLE_STYLE_RE = re.compile(r'(\bstyle\s*=\s*")([^"]*)(")', re.IGNORECASE | re.DOTALL)
_SINGLE_STYLE_RE = re.compile(r"(\bstyle\s*=\s*')([^']*)(')", re.IGNORECASE | re.DOTALL)
_STYLESHEET_HREF_RE = re.compile(
    r"<link\b[^>]*\brel\s*=\s*['\"][^'\"]*stylesheet[^'\"]*['\"][^>]*\bhref\s*=\s*['\"]([^'\"]+)['\"]"
    r"|<link\b[^>]*\bhref\s*=\s*['\"]([^'\"]+)['\"][^>]*\brel\s*=\s*['\"][^'\"]*stylesheet[^'\"]*['\"]",
    re.IGNORECASE,
)


@dataclass
class TypographyMutationStats:
    stylesheet_links_added: int = 0
    css_font_sizes_normalized: int = 0
    css_line_heights_normalized: int = 0
    inline_style_attributes_changed: int = 0
    inline_style_blocks_changed: int = 0


@dataclass(frozen=True)
class TypographyIssue:
    severity: str
    code: str
    message: str
    href: str = ""


@dataclass
class TypographyReport:
    mode: str
    profile: str
    status: str
    score: int
    documents_checked: int = 0
    documents_with_profile: int = 0
    css_files_checked: int = 0
    mutations: TypographyMutationStats = field(default_factory=TypographyMutationStats)
    issues: list[TypographyIssue] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def typography_profile_css(config: TypographyConfig) -> str:
    if config.profile != "koreader-literary":
        raise ValueError(f"unsupported typography profile: {config.profile}")
    return KOREADER_LITERARY_CSS


def _format_em(value: float) -> str:
    if value == 0:
        return "0"
    return f"{value:.4f}".rstrip("0").rstrip(".") + "em"


def normalize_css_typography(
    css: str,
    config: TypographyConfig,
    stats: TypographyMutationStats | None = None,
) -> str:
    stats = stats or TypographyMutationStats()

    def replace(match: re.Match[str]) -> str:
        property_name = match.group("property").lower()
        if property_name == "font-size" and not config.normalize_fixed_font_sizes:
            return match.group(0)
        if property_name == "line-height" and not config.normalize_absolute_line_heights:
            return match.group(0)

        value = float(match.group("value"))
        unit = match.group("unit").lower()
        em_value = value / (16.0 if unit == "px" else 12.0)
        if property_name == "font-size":
            stats.css_font_sizes_normalized += 1
        else:
            stats.css_line_heights_normalized += 1
        return match.group("prefix") + _format_em(em_value)

    parts = re.split(r"(/\*.*?\*/)", css, flags=re.DOTALL)
    return "".join(
        part if index % 2 else _ABSOLUTE_TYPOGRAPHY_RE.sub(replace, part)
        for index, part in enumerate(parts)
    )


def normalize_markup_typography(
    raw_markup: bytes,
    config: TypographyConfig,
    stats: TypographyMutationStats | None = None,
) -> bytes:
    if not config.normalize_inline_styles:
        return raw_markup
    stats = stats or TypographyMutationStats()
    decoded = decode_markup(raw_markup)
    if not decoded.reliable:
        return raw_markup

    text = decoded.text

    def replace_style_block(match: re.Match[str]) -> str:
        normalized = normalize_css_typography(match.group(2), config, stats)
        if normalized != match.group(2):
            stats.inline_style_blocks_changed += 1
        return match.group(1) + normalized + match.group(3)

    def replace_style_attribute(match: re.Match[str]) -> str:
        normalized = normalize_css_typography(match.group(2), config, stats)
        if normalized != match.group(2):
            stats.inline_style_attributes_changed += 1
        return match.group(1) + normalized + match.group(3)

    text = _STYLE_BLOCK_RE.sub(replace_style_block, text)
    text = _DOUBLE_STYLE_RE.sub(replace_style_attribute, text)
    text = _SINGLE_STYLE_RE.sub(replace_style_attribute, text)
    try:
        return text.encode(decoded.encoding)
    except (LookupError, UnicodeEncodeError):
        return raw_markup


def normalize_css_bytes(
    raw_css: bytes,
    config: TypographyConfig,
    stats: TypographyMutationStats | None = None,
) -> bytes:
    decoded = decode_css(raw_css)
    if not decoded.reliable:
        return raw_css
    normalized = normalize_css_typography(decoded.text, config, stats)
    try:
        return normalized.encode(decoded.encoding)
    except (LookupError, UnicodeEncodeError):
        return raw_css


def _opf_root_path(entries: dict[str, bytes]) -> str:
    container_ns = {"container": "urn:oasis:names:tc:opendocument:xmlns:container"}
    container = ElementTree.fromstring(entries["META-INF/container.xml"])
    rootfile = container.find(".//container:rootfile", container_ns)
    if rootfile is None or not rootfile.attrib.get("full-path", "").strip():
        raise ValueError("EPUB container has no rootfile")
    return rootfile.attrib["full-path"].strip()


def _opf_tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}" if namespace else name


def _score(issues: list[TypographyIssue]) -> int:
    penalties = {"HIGH": 25, "MEDIUM": 10, "LOW": 3}
    return max(0, 100 - sum(penalties.get(issue.severity.upper(), 3) for issue in issues))


def _stylesheet_hrefs(markup: str) -> list[str]:
    hrefs: list[str] = []
    for match in _STYLESHEET_HREF_RE.finditer(markup):
        href = match.group(1) or match.group(2)
        if href:
            hrefs.append(href.split("#", 1)[0].split("?", 1)[0])
    return hrefs


def _markup_has_absolute_typography(markup: str) -> bool:
    fragments = [match.group(2) for match in _STYLE_BLOCK_RE.finditer(markup)]
    fragments.extend(match.group(2) for match in _DOUBLE_STYLE_RE.finditer(markup))
    fragments.extend(match.group(2) for match in _SINGLE_STYLE_RE.finditer(markup))
    return any(_ABSOLUTE_TYPOGRAPHY_RE.search(fragment) for fragment in fragments)


def _css_has_absolute_typography(css: str) -> bool:
    without_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    return _ABSOLUTE_TYPOGRAPHY_RE.search(without_comments) is not None


def audit_epub_typography(
    epub_path: Path,
    config: TypographyConfig,
    stats: TypographyMutationStats | None = None,
) -> TypographyReport:
    mutations = stats or TypographyMutationStats()
    if config.mode == TypographyMode.OFF:
        return TypographyReport(
            mode=config.mode.value,
            profile=config.profile,
            status="skipped",
            score=0,
            mutations=mutations,
        )

    with zipfile.ZipFile(epub_path, "r") as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}

    opf_path = _opf_root_path(entries)
    opf = ElementTree.fromstring(entries[opf_path])
    namespace = opf.tag[1:].split("}", 1)[0] if opf.tag.startswith("{") else ""

    def q(name: str) -> str:
        return _opf_tag(namespace, name)

    opf_dir = posixpath.dirname(opf_path)
    manifest = opf.find(q("manifest"))
    items = [] if manifest is None else list(manifest.findall(q("item")))

    profile_paths: set[str] = set()
    document_paths: list[str] = []
    css_paths: list[str] = []
    for item in items:
        href = item.attrib.get("href", "").strip()
        if not href:
            continue
        archive_path = posixpath.normpath(posixpath.join(opf_dir, href))
        media_type = item.attrib.get("media-type", "")
        properties = {token.lower() for token in item.attrib.get("properties", "").split()}
        if item.attrib.get("id") == "hermes-normalized-css" or href.endswith("hermes-normalized.css"):
            profile_paths.add(archive_path)
        if media_type == "text/css":
            css_paths.append(archive_path)
        elif media_type in {"application/xhtml+xml", "text/html"} and "nav" not in properties:
            document_paths.append(archive_path)

    issues: list[TypographyIssue] = []
    documents_with_profile = 0
    for document_path in document_paths:
        raw = entries.get(document_path)
        if raw is None:
            issues.append(
                TypographyIssue("HIGH", "MISSING_DOCUMENT", "Manifest document is missing", document_path)
            )
            continue
        decoded = decode_markup(raw)
        markup = decoded.text
        resolved_links = {
            posixpath.normpath(posixpath.join(posixpath.dirname(document_path), href))
            for href in _stylesheet_hrefs(markup)
        }
        if resolved_links & profile_paths:
            documents_with_profile += 1
        elif config.require_profile_link:
            issues.append(
                TypographyIssue(
                    "HIGH",
                    "PROFILE_NOT_LINKED",
                    "Readable document does not link the Hermes typography profile",
                    document_path,
                )
            )
        if _markup_has_absolute_typography(markup):
            issues.append(
                TypographyIssue(
                    "HIGH",
                    "INLINE_ABSOLUTE_TYPOGRAPHY",
                    "Inline CSS still uses px/pt font-size or line-height",
                    document_path,
                )
            )
        if re.search(r"<font\b", markup, re.IGNORECASE):
            issues.append(
                TypographyIssue(
                    "LOW",
                    "DEPRECATED_FONT_ELEMENT",
                    "Deprecated font elements are neutralized by the profile but remain in source markup",
                    document_path,
                )
            )
        if re.search(r"(?:<br\s*/?>\s*){3,}", markup, re.IGNORECASE):
            issues.append(
                TypographyIssue(
                    "LOW",
                    "REPEATED_BREAK_SPACING",
                    "Document uses repeated line breaks for vertical spacing",
                    document_path,
                )
            )

    for css_path in css_paths:
        raw = entries.get(css_path)
        if raw is None:
            issues.append(TypographyIssue("HIGH", "MISSING_CSS", "Manifest CSS is missing", css_path))
            continue
        css = decode_css(raw).text
        if css_path not in profile_paths and _css_has_absolute_typography(css):
            issues.append(
                TypographyIssue(
                    "HIGH",
                    "CSS_ABSOLUTE_TYPOGRAPHY",
                    "CSS still uses px/pt font-size or line-height",
                    css_path,
                )
            )
        if css_path not in profile_paths and re.search(r"@font-face\b", css, re.IGNORECASE):
            issues.append(
                TypographyIssue(
                    "MEDIUM",
                    "EMBEDDED_FONT_FACE",
                    "Embedded font is preserved; review its size and KOReader override behavior",
                    css_path,
                )
            )

    if config.require_profile_link and not profile_paths:
        issues.append(
            TypographyIssue(
                "HIGH",
                "PROFILE_STYLESHEET_MISSING",
                "Hermes typography profile is not present in the EPUB manifest",
            )
        )

    status = "passed"
    if any(issue.severity == "HIGH" for issue in issues):
        status = "failed"
    elif issues:
        status = "warnings"
    return TypographyReport(
        mode=config.mode.value,
        profile=config.profile,
        status=status,
        score=_score(issues),
        documents_checked=len(document_paths),
        documents_with_profile=documents_with_profile,
        css_files_checked=len(css_paths),
        mutations=mutations,
        issues=issues,
    )


def skipped_typography_report(config: TypographyConfig, reason: str) -> TypographyReport:
    return TypographyReport(
        mode=config.mode.value,
        profile=config.profile,
        status="skipped",
        score=0,
        errors=[reason],
    )


def write_typography_reports(report: TypographyReport, reports_dir: Path) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "typography-report.json").write_text(report.to_json(), encoding="utf-8")
    lines = [
        "# Typography report",
        "",
        f"Mode: {report.mode}",
        f"Profile: {report.profile}",
        f"Status: {report.status}",
        f"Score: {report.score}",
        f"Documents: {report.documents_with_profile}/{report.documents_checked} linked",
        f"CSS files: {report.css_files_checked}",
        "",
        "## Deterministic changes",
        "",
        f"- Stylesheet links added: {report.mutations.stylesheet_links_added}",
        f"- Fixed font sizes converted to em: {report.mutations.css_font_sizes_normalized}",
        f"- Absolute line heights converted to em: {report.mutations.css_line_heights_normalized}",
        f"- Inline style attributes changed: {report.mutations.inline_style_attributes_changed}",
        f"- Inline style blocks changed: {report.mutations.inline_style_blocks_changed}",
        "",
        "## Issues",
        "",
    ]
    if report.issues:
        for issue in report.issues:
            lines.append(f"- [{issue.severity}] {issue.code}: {issue.message} {issue.href}".rstrip())
    else:
        lines.append("- None")
    if report.errors:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {error}" for error in report.errors)
    (reports_dir / "typography-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
