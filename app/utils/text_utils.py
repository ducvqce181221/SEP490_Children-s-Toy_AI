from __future__ import annotations

import re
import unicodedata

_RAW_HARD_PROFANITY_WORDS = (
    "cặc",
    "lồn",
    "địt",
    "đéo",
    "buồi",
    "chó đẻ",
    "khốn nạn",
    "mất dạy",
    "rác rưởi",
)

_LEET_MAP = str.maketrans({
    "@": "a",
    "$": "s",
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "|": "i",
})

_HARD_PROFANITY_PATTERNS = (
    r"\bcon\s*cac\b",
    r"\bcon\s*kac\b",
    r"\bcon\s*cak\b",
    r"\bcon\s*cax\b",
    r"\bkac\b",
    r"\bcak\b",
    r"\bcax\b",
    r"\bcka\b",
    r"\bkak\b",
    r"\blon\b",
    r"\bloz\b",
    r"\blozl\b",
    r"\bl0n\b",
    r"\bdit\b",
    r"\bdjt\b",
    r"\bdech\b",
    r"\bdeo\b",
    r"\bde0\b",
    r"\bcon\s*cko\b",
    r"\bcon\s*cho\b",
    r"\bcho\s*de\b",
    r"\bdm\b",
    r"\bdmm\b",
    r"\bclm\b",
    r"\bclmm\b",
)

_HARD_PROFANITY_REGEX = [re.compile(p, re.IGNORECASE) for p in _HARD_PROFANITY_PATTERNS]

_OBFUSCATED_TERMS = (
    "cac",
    "kac",
    "cak",
    "cax",
    "lon",
    "dit",
    "djt",
    "deo",
    "cho",
)


def _build_obfuscated_word_pattern(word: str) -> re.Pattern[str]:
    letters = [re.escape(ch) for ch in word]
    middle = r"[\W_]*".join(letters)
    return re.compile(rf"(?<![a-z0-9]){middle}(?![a-z0-9])", re.IGNORECASE)


_OBFUSCATED_WORD_REGEX = [_build_obfuscated_word_pattern(term) for term in _OBFUSCATED_TERMS]


def normalize_vietnamese_text(text: str | None) -> str:
    """
    Normalize for moderation matching:
    - lowercase
    - leetspeak canonicalization
    - Vietnamese diacritics removal
    - keep token boundaries (whitespace preserved, no global concatenation)
    """
    base = (text or "").strip().lower()
    if not base:
        return ""
    base = base.translate(_LEET_MAP).replace("đ", "d")
    decomposed = unicodedata.normalize("NFKD", base)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_marks)


def has_hard_profanity(text: str | None) -> bool:
    """
    Hard profanity detector designed to avoid substring false positives:
    - match by boundaries/tokens
    - allow obfuscation with punctuation or spacing between letters
    - never concatenate all words into one string for substring scans
    """
    if not text:
        return False

    lower_text = text.lower()
    if any(word in lower_text for word in _RAW_HARD_PROFANITY_WORDS):
        return True

    normalized = normalize_vietnamese_text(text)
    if any(pattern.search(normalized) for pattern in _HARD_PROFANITY_REGEX):
        return True

    if any(pattern.search(normalized) for pattern in _OBFUSCATED_WORD_REGEX):
        return True

    return False
