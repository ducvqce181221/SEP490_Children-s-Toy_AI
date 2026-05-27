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
)

_HARD_PROFANITY_PATTERNS = (
    # cặc / cạc / kặc / kac / cax / cak variations (only unambiguous ones)
    r"\bcon\s*cac\b",
    r"\bcon\s*kac\b",
    r"\bcon\s*cak\b",
    r"\bcon\s*cax\b",
    r"\bkac\b",
    r"\bcak\b",
    r"\bcax\b",
    r"\bcka\b",
    r"\bkak\b",
    
    # lồn / loz / l0n / lozl
    r"\blo[ln]\b",
    r"\bloz\b",
    r"\blozl\b",
    r"\bl0n\b",
    
    # địt / djt / đệch
    r"\bdit\b",
    r"\bdjt\b",
    r"\bdech\b",
    
    # đéo / deo / de0
    r"\bdeo\b",
    r"\bde0\b",
    
    # chó / cko / cko's
    r"\bcon\s*cko\b",
    r"\bcon\s*cho\b",
    r"\bcko\b",
    r"\bcho\s*de\b",
    r"\bcho\s*ma\b",
    r"\bcho\s*dua\b",
    r"\bcho\s*ho\b",
    r"\bcho\s*san\b",
    
    # đm / dmm / clm / clmm / vcl
    r"\bdm\b",
    r"\bdmm\b",
    r"\bclm\b",
    r"\bclmm\b",
    r"\bvcl\b",
    r"\bcl\b",
    r"\bsml\b",
    r"\bsm[ln]\b",
    r"\bvl\b",
    
    # Other common vulgar phrases
    r"\bb[uO]di\b",
    r"\bbuoi\b",
    r"\bbua\b",
    r"\bvai\b",
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
    Uses raw check for accented words first, and normalized text for teen-code.
    """
    if not text:
        return False
    
    # 1. Raw check for accented vulgar words
    lower_text = text.lower()
    if any(word in lower_text for word in _RAW_HARD_PROFANITY_WORDS):
        return True
        
    # 2. Check unaccented / teen code variations after normalization
    normalized = normalize_vietnamese_text(text)
    return any(pattern.search(normalized) for pattern in _HARD_PROFANITY_REGEX)

