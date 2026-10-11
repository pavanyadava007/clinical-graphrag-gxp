"""Pure text helpers shared by the pipeline, retrieval and the citation check (no Spark needed)."""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")
# Leading section heading as printed in SPL text, e.g. "1 INDICATIONS AND USAGE" or "BOXED WARNING".
_HEADING = re.compile(r"^\s*(?:\d+(?:\.\d+)*\s+)?[A-Z][A-Z &/,\-()]{3,80}?(?=\s+[A-Z][a-z]|\s+\d|\s*$)")


def clean_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("•", " ").replace(" ", " ")
    return _WS.sub(" ", s).strip()


def strip_heading(s: str) -> str:
    m = _HEADING.match(s)
    if m and len(s) - m.end() > 40:
        return s[m.end():].strip()
    return s


def norm_for_match(s: str) -> str:
    """Normalisation used to check that a quoted span exists in a section (case and whitespace insensitive)."""
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[‐-―]", "-", s)
    return _WS.sub(" ", s).strip().strip(".").strip()


def chunk_text(text: str, size: int, overlap: int) -> list[tuple[int, int, str]]:
    """Split text into overlapping windows on whitespace boundaries. Returns (start, end, chunk)."""
    if size <= overlap:
        raise ValueError("size must be larger than overlap")
    out: list[tuple[int, int, str]] = []
    n = len(text)
    start = 0
    while start < n:
        end = min(n, start + size)
        if end < n:
            cut = text.rfind(" ", start + size // 2, end)
            if cut > start:
                end = cut
        out.append((start, end, text[start:end].strip()))
        if end >= n:
            break
        nxt = end - overlap
        sp = text.find(" ", nxt)
        start = sp + 1 if 0 <= sp < end else nxt
    return out


def strip_class_suffix(name: str) -> str:
    return re.sub(r"\s*\[(EPC|MoA|PE|CS|Chemical/Ingredient)\]\s*$", "", name or "").strip()
