from __future__ import annotations

import re
import unicodedata

_HARD_PROFANITY_PATTERNS = (
    r"\bcon\s*cac\b",
    r"\bcac\b",
    r"\bdit\b",
    r"\bdm\b",
    r"\bdmm\b",
    r"\bcl\b",
    r"\blo[ln]\b",
    r"\bvai\b",
    r"\bcho\s*de\b",
)

_HARD_PROFANITY_REGEX = [re.compile(p, re.IGNORECASE) for p in _HARD_PROFANITY_PATTERNS]


def normalize_vietnamese_text(text: str | None) -> str:
    """
    Normalize Vietnamese text by removing accents/diacritics,
    converting to lowercase, replacing 'đ' with 'd', and normalizing whitespace.
    """
    base = (text or "").strip().lower()
    if not base:
        return ""
    base = base.replace("đ", "d")
    decomposed = unicodedata.normalize("NFKD", base)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_marks)


def has_hard_profanity(text: str | None) -> bool:
    """
    Quick local check to detect if text contains extremely vulgar Vietnamese swear words.
    Uses normalized text for robust detection.
    """
    if not text:
        return False
    normalized = normalize_vietnamese_text(text)
    return any(pattern.search(normalized) for pattern in _HARD_PROFANITY_REGEX)
