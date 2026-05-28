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
    
    # lồn / loz / l0n / lozl (lol is removed to let LLM evaluate it contextually)
    r"\blon\b",
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
    
    # chó / cko variations (unambiguous insults)
    r"\bcon\s*cko\b",
    r"\bcon\s*cho\b",
    r"\bcho\s*de\b",
    
    # đm / dmm / clm / clmm (vcl/vl/cl/sml removed to let LLM evaluate contextually)
    r"\bdm\b",
    r"\bdmm\b",
    r"\bclm\b",
    r"\bclmm\b",
)

_HARD_PROFANITY_REGEX = [re.compile(p, re.IGNORECASE) for p in _HARD_PROFANITY_PATTERNS]

_COMPACT_HARD_PROFANITY_KEYWORDS = (
    "concac", "conkac", "concak", "concax", "conlon", "condit", "condjt",
    "ditconme", "djtconme", "djtme", "ditme", "chode",
    "khonnan", "matday", "racruoi",
)


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
    Uses:
      1. Raw check for accented vulgar words (before diacritics removal).
      2. Normalized regex search for unaccented severe words.
      3. Compact (spacing-stripped) keyword check to counter formatting bypasses.
    """
    if not text:
        return False
    
    # 1. Raw check for accented vulgar words
    lower_text = text.lower()
    if any(word in lower_text for word in _RAW_HARD_PROFANITY_WORDS):
        return True
        
    # 2. Check unaccented / teen code variations after normalization
    normalized = normalize_vietnamese_text(text)
    if any(pattern.search(normalized) for pattern in _HARD_PROFANITY_REGEX):
        return True
        
    # 3. Compact space/punctuation-stripped bypass counter check
    compact = "".join(ch for ch in normalized if ch.isalnum())
    if any(kw in compact for kw in _COMPACT_HARD_PROFANITY_KEYWORDS):
        return True
        
    return False
