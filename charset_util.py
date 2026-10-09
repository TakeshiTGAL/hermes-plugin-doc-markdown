"""Decode HTTP bodies using Content-Type charset and HTML meta charset."""

from __future__ import annotations

import codecs
import re
from typing import Optional, Tuple

# Skip tags that contain http-equiv. A bare charset= search also matches
# the charset inside an earlier http-equiv, which would hide a later
# <meta charset> (the table prefers meta charset, then http-equiv).
_META_CHARSET_RE = re.compile(
    rb"""<meta\b(?![^>]*\bhttp-equiv\b)[^>]*?\bcharset\s*=\s*["']?\s*([a-zA-Z0-9_.:-]+)""",
    re.IGNORECASE,
)
_META_CONTENT_TYPE_RE = re.compile(
    rb"""<meta\b[^>]*?\bhttp-equiv\s*=\s*["']?content-type["']?[^>]*?\bcontent\s*=\s*["'][^"']*charset\s*=\s*([a-zA-Z0-9_.:-]+)""",
    re.IGNORECASE,
)


def parse_content_type(header: str) -> Tuple[str, Optional[str]]:
    """Return (media_type_lower, charset_or_None) from a Content-Type header."""
    if not header:
        return "", None
    parts = [p.strip() for p in header.split(";")]
    media = parts[0].lower() if parts else ""
    charset: Optional[str] = None
    for part in parts[1:]:
        if not part:
            continue
        key, _, value = part.partition("=")
        if key.strip().lower() == "charset" and value:
            charset = value.strip().strip("\"'")
            break
    return media, charset


# Japanese Shift_JIS-family labels → cp932 so machine-dependent glyphs
# (①, 髙, 﨑, ～, －) decode instead of becoming U+FFFD.
# Labels are compared after lowercasing and turning "_" into "-".
_CP932_LABELS = frozenset(
    {
        "shift-jis",
        "sjis",
        "x-sjis",
        "windows-31j",
        "ms-kanji",
        "ms932",
        "csshiftjis",
        "cp932",
    }
)


def _charset_label(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def normalize_charset(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    if _charset_label(name) in _CP932_LABELS:
        return "cp932"
    try:
        resolved = codecs.lookup(name.strip()).name
    except LookupError:
        return None
    if _charset_label(resolved) in _CP932_LABELS:
        return "cp932"
    return resolved


def html_meta_label(data: bytes) -> Optional[str]:
    """Raw charset label from the first ~8 KiB, or None when no meta names one."""
    sample = data[:8192]
    match = _META_CHARSET_RE.search(sample) or _META_CONTENT_TYPE_RE.search(sample)
    if not match:
        return None
    label = match.group(1).decode("ascii", errors="ignore").strip()
    return label or None


def charset_from_html_meta(data: bytes) -> Optional[str]:
    """Known charset from the first ~8 KiB: <meta charset>, else http-equiv."""
    label = html_meta_label(data)
    if label is None:
        return None
    return normalize_charset(label)


def resolve_text_charset(
    content_type_header: str,
    body: bytes,
    *,
    html: bool = False,
) -> str:
    """Charset from Content-Type, then HTML meta; default utf-8."""
    _, header_charset = parse_content_type(content_type_header)
    resolved = normalize_charset(header_charset)
    if resolved:
        return resolved
    if html:
        meta = charset_from_html_meta(body)
        if meta:
            return meta
    return "utf-8"


def decode_body(data: bytes, charset: str) -> str:
    """Decode *data* with *charset*; unknown encodings fall back to utf-8."""
    encoding = normalize_charset(charset) or "utf-8"
    try:
        return data.decode(encoding, errors="replace")
    except Exception:
        return data.decode("utf-8", errors="replace")


def truncate_with_marker(text: str, limit: int) -> str:
    """Clip *text* to *limit* and append a visible truncation marker.

    The marker is never clipped. When *limit* is shorter than the note, none
    of the original text is kept, and the note says 0 characters were kept
    so the limit is not read as a remaining count.
    """
    if len(text) <= limit:
        return text
    marker = f"\n\n[truncated: {limit} of {len(text)} characters]"
    if limit <= len(marker):
        return (
            f"[truncated: 0 of {len(text)} characters kept; "
            f"limit {limit} is shorter than this note]"
        )
    return text[: limit - len(marker)] + marker
