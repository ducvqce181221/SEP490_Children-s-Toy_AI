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
    "kac",
    "cak",
    "cax",
    "lon",
    "dit",
    "djt",
    "deo",
)

def _build_obfuscated_word_pattern(word: str) -> re.Pattern[str]:
    letters = [re.escape(ch) for ch in word]
    middle = r"[\W_]*".join(letters)
    return re.compile(rf"(?<![a-z0-9]){middle}(?![a-z0-9])", re.IGNORECASE)


def _build_obfuscated_phrase_pattern(*words: str) -> re.Pattern[str]:
    parts = [r"[\W_]*".join(re.escape(ch) for ch in word) for word in words]
    return re.compile(rf"(?<![a-z0-9]){r'[\W_]+'.join(parts)}(?![a-z0-9])", re.IGNORECASE)


_OBFUSCATED_PHRASE_REGEX = [
    _build_obfuscated_phrase_pattern("con", "cac"),
    _build_obfuscated_phrase_pattern("con", "kac"),
    _build_obfuscated_phrase_pattern("con", "cak"),
    _build_obfuscated_phrase_pattern("con", "cax"),
    _build_obfuscated_phrase_pattern("con", "cko"),
    _build_obfuscated_phrase_pattern("cho", "de"),
]


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


_DIGIT_WORDS_MAP = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "khong": "0", "mot": "1", "hai": "2", "ba": "3", "bon": "4",
    "nam": "5", "sau": "6", "bay": "7", "tam": "8", "chin": "9",
    "k0": "0"
}


def clean_and_normalize_text(text: str | None) -> str:
    """
    Unified advanced normalization pipeline for both review text and OCR text.
    Handles:
      - Lowercasing and diacritics removal (unaccented base representation)
      - Telex/VNI style teencode normalization (e.g. ne^u -> neu, ba.n -> ban, muo^'n -> muon)
      - Number words to digits conversion (e.g. zero nine -> 09)
      - Collapsing spaced-out words and phone numbers (e.g. g un -> gun, 0 9 -> 09)
    """
    if not text:
        return ""

    # Convert to lowercase
    val = text.lower().strip()

    # 1. First round of Telex/VNI symbols mapping inside words
    val = val.replace("e^", "e").replace("o^", "o").replace("a^", "a")
    val = val.replace("o+", "o").replace("u+", "u").replace("a+", "a")
    val = val.replace("o*", "o").replace("u*", "u").replace("a*", "a")
    
    # We replace "ow", "uw", "aw" on word level to avoid breaking English words
    english_ow_words = {
        "below", "how", "now", "low", "show", "grow", "slow", "down", "town", "brown",
        "flower", "power", "allow", "window", "yellow", "shadow", "row", "blow", "snow",
        "throw", "crow", "know", "bow", "cow", "own", "owner", "ownership", "showing",
        "growing", "knowing", "lower", "lowest"
    }

    words = val.split()
    telex_cleaned_words = []
    for word in words:
        if word in english_ow_words or any(word.startswith(eng) for eng in english_ow_words if len(eng) > 3):
            telex_cleaned_words.append(word)
        else:
            w_replaced = word.replace("ow", "o").replace("uw", "u").replace("aw", "a")
            telex_cleaned_words.append(w_replaced)
            
    val = " ".join(telex_cleaned_words)
    val = val.replace("đ", "d").replace("dd", "d")

    val = re.sub(r"[\^\+\*\\]", "", val)

    # Trailing VNI/Telex tone markers like 's, 'f, 'r, 'x, 'j, '1, '2, etc. (e.g. cko's -> cko)
    val = re.sub(r"['``]([sfrxj1-589])\b", "", val)
    # Strip standalone tone marks at word boundary
    val = re.sub(r"['``](?=\s|$)", "", val)
    # Strip tone marks inside words (e.g. muo'n -> muon, ha`ng -> hang)
    val = re.sub(r"(?<=[a-zA-Z])['``](?=[a-zA-Z])", "", val)

    # 2. Decompose and remove standard Unicode combining marks (accents)
    decomposed = unicodedata.normalize("NFKD", val)
    val = "".join(ch for ch in decomposed if not unicodedata.combining(ch))

    # 3. Clean up words (remove remaining diacritics/punctuation from ends/inside)
    words = val.split()
    cleaned_words = []
    for word in words:
        if word.isdigit():
            cleaned_word = word
        else:
            # Strip VNI trailing tone digits (1-5, 8-9) if attached to word
            w_clean = re.sub(r"(?<=[a-zA-Z])[1-589]\b", "", word)
            cleaned_chars = []
            for ch in w_clean:
                if ch.isalnum():
                    cleaned_chars.append(ch)
            cleaned_word = "".join(cleaned_chars)
        if cleaned_word:
            cleaned_words.append(cleaned_word)

    normalized_text = " ".join(cleaned_words)

    # 4. Convert written-word digits to numeric forms
    words = normalized_text.split()
    mapped_words = []
    for w in words:
        if w in _DIGIT_WORDS_MAP:
            mapped_words.append(_DIGIT_WORDS_MAP[w])
        else:
            mapped_words.append(w)
    normalized_text = " ".join(mapped_words)

    # 5. Collapse spaces
    # Collapse spaces between adjacent digits (e.g., "0 9 1 2" -> "0912")
    normalized_text = re.sub(r"(?<=\d)\s+(?=\d)", "", normalized_text)

    # Collapse spaces in known obfuscated words like "g un", "s d t"
    normalized_text = re.sub(r"\bg\s+un\b", "gun", normalized_text)
    normalized_text = re.sub(r"\bs\s+d\s+t\b", "sdt", normalized_text)

    # General collapsing of adjacent single characters if needed
    prev_text = ""
    while normalized_text != prev_text:
        prev_text = normalized_text
        normalized_text = re.sub(r"\b([a-hj-np-z0-9])\s+([a-hj-np-z0-9])\b", r"\1\2", normalized_text)

    return re.sub(r"\s+", " ", normalized_text).strip()


def has_hard_profanity(text: str | None) -> bool:
    """
    Hard profanity detector designed to avoid substring false positives:
    - match by boundaries/tokens
    - allow obfuscation with punctuation or spacing between letters
    - never concatenate all words into one string for substring scans
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
        
    # 3. Contextual obfuscated phrase check for ambiguous Vietnamese tokens.
    if any(pattern.search(normalized) for pattern in _OBFUSCATED_PHRASE_REGEX):
        return True

    # 4. Obfuscated token check with boundaries to avoid substring false positives
    if any(pattern.search(normalized) for pattern in _OBFUSCATED_WORD_REGEX):
        return True

    return False
