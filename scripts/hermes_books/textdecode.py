from __future__ import annotations

import codecs
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DecodedText:
    text: str
    encoding: str
    reliable: bool


_BOMS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def _bom_encoding(raw: bytes) -> str:
    for bom, encoding in _BOMS:
        if raw.startswith(bom):
            return encoding
    return ""


def _utf16_pattern_encoding(raw: bytes) -> str:
    if raw.startswith(b"<\x00?\x00x\x00m\x00l\x00") or raw.startswith(b"<\x00h\x00t\x00m\x00l\x00"):
        return "utf-16-le"
    if raw.startswith(b"\x00<\x00?\x00x\x00m\x00l") or raw.startswith(b"\x00<\x00h\x00t\x00m\x00l"):
        return "utf-16-be"
    return ""


def _nul_interleaved_encoding(raw: bytes) -> str:
    sample = raw[:1024]
    if len(sample) < 16:
        return ""

    quad_count = len(sample) // 4
    if quad_count >= 4:
        quad_ratios = [sample[index::4].count(0) / quad_count for index in range(4)]
        if quad_ratios[1] > 0.6 and quad_ratios[2] > 0.6 and quad_ratios[3] > 0.6:
            return "utf-32-le"
        if quad_ratios[0] > 0.6 and quad_ratios[1] > 0.6 and quad_ratios[2] > 0.6:
            return "utf-32-be"

    pair_count = len(sample) // 2
    even_ratio = sample[0::2].count(0) / pair_count
    odd_ratio = sample[1::2].count(0) / pair_count
    if odd_ratio > 0.35 and even_ratio < 0.10:
        return "utf-16-le"
    if even_ratio > 0.35 and odd_ratio < 0.10:
        return "utf-16-be"
    return ""


def _ascii_preview(raw: bytes, limit: int = 2048) -> str:
    return raw[:limit].decode("latin-1", errors="ignore")


def _declared_markup_encoding(raw: bytes) -> str:
    preview = _ascii_preview(raw)
    xml_match = re.search(r"<\?xml[^>]+encoding\s*=\s*['\"]([^'\"]+)['\"]", preview, re.IGNORECASE)
    if xml_match:
        return xml_match.group(1).strip()
    meta_match = re.search(r"<meta[^>]+charset\s*=\s*['\"]?\s*([A-Za-z0-9._:-]+)", preview, re.IGNORECASE)
    if meta_match:
        return meta_match.group(1).strip()
    content_match = re.search(r"<meta[^>]+content\s*=\s*['\"][^'\"]*charset=([A-Za-z0-9._:-]+)", preview, re.IGNORECASE)
    if content_match:
        return content_match.group(1).strip()
    return ""


def _declared_css_encoding(raw: bytes) -> str:
    preview = _ascii_preview(raw)
    match = re.search(r"@charset\s+['\"]([^'\"]+)['\"]", preview, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _decode_with_detection(raw: bytes, declared: str, default: str = "utf-8") -> DecodedText:
    encoding = _bom_encoding(raw) or _utf16_pattern_encoding(raw) or _nul_interleaved_encoding(raw) or declared or default
    try:
        text = raw.decode(encoding, errors="strict")
        return DecodedText(text, encoding, not (encoding == default and "\x00" in text))
    except (LookupError, UnicodeDecodeError):
        try:
            return DecodedText(raw.decode(default, errors="strict"), default, False)
        except UnicodeDecodeError:
            return DecodedText(raw.decode(default, errors="replace"), default, False)


def decode_markup(raw: bytes) -> DecodedText:
    return _decode_with_detection(raw, _declared_markup_encoding(raw))


def decode_css(raw: bytes) -> DecodedText:
    return _decode_with_detection(raw, _declared_css_encoding(raw))
