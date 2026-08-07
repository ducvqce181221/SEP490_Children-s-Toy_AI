"""
app/utils/text_utils.py
-----------------------
Tập hợp các tiện ích xử lý và chuẩn hóa văn bản Tiếng Việt cho hệ thống kiểm duyệt AI.

Bao gồm các chức năng chính:
1. Phát hiện từ tục tĩu, chửi thề cực đoan (Hard Profanity) tiếng Việt có dấu, không dấu và teen code.
2. Nhận diện các từ/cụm từ cố tình chèn ký tự đặc biệt hoặc khoảng trắng để lách luật (Obfuscation Detection).
3. Chuẩn hóa teencode Telex/VNI, chuyển chữ số bằng chữ sang dạng số (VD: "không chín" -> "09").
4. Gộp các từ/số điện thoại bị gõ cách rời rạc (VD: "0 9 1 2" -> "0912", "g un" -> "gun").
5. Phân tách cụm đồ họa Grapheme Clusters để phát hiện và ngăn chặn Spam Emoji / Ký tự lặp lại liên tiếp.
"""

from __future__ import annotations

import re
import unicodedata

# 1. Danh sách các từ tục tĩu / chửi thề thô cực đoan tiếng Việt nguyên bản (có dấu)
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
    "cức",
)

# 2. Bảng ánh xạ ký tự Leetspeak (chữ viết thay thế ký tự đặc biệt) về chữ cái nguyên bản
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

# 3. Các biểu thức chính quy (Regex) bắt các biến thể Teen Code và chửi thề không dấu
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
    r"\bcuc\b",
    r"\bcuk\b",
)

_HARD_PROFANITY_REGEX = [re.compile(p, re.IGNORECASE) for p in _HARD_PROFANITY_PATTERNS]

# 4. Danh sách các thuật ngữ bị cố ý chèn khoảng trắng/ký tự phân cách ở giữa để lách luật
_OBFUSCATED_TERMS = (
    "kac",
    "cak",
    "cax",
    "lon",
    "dit",
    "djt",
    "deo",
    "cuc",
    "cuk",
)


def _build_obfuscated_word_pattern(word: str) -> re.Pattern[str]:
    """Tạo Regex nhận diện từ tục tĩu bị cố tình chèn ký tự không phải chữ ([\\W_]*) giữa các chữ cái."""
    letters = [re.escape(ch) for ch in word]
    middle = r"[\W_]*".join(letters)
    return re.compile(rf"(?<![a-z0-9]){middle}(?![a-z0-9])", re.IGNORECASE)


def _build_obfuscated_phrase_pattern(*words: str) -> re.Pattern[str]:
    """Tạo Regex nhận diện cụm từ tục tĩu bị chèn khoảng trắng hoặc ký tự đặc biệt giữa các từ."""
    parts = [r"[\W_]*".join(re.escape(ch) for ch in word) for word in words]
    pattern_str = r"[\W_]+".join(parts)
    return re.compile(rf"(?<![a-z0-9]){pattern_str}(?![a-z0-9])", re.IGNORECASE)


# Khởi tạo các mẫu Regex cho cụm từ tục tĩu bị giấu (Obfuscated phrases)
_OBFUSCATED_PHRASE_REGEX = [
    _build_obfuscated_phrase_pattern("con", "cac"),
    _build_obfuscated_phrase_pattern("con", "kac"),
    _build_obfuscated_phrase_pattern("con", "cak"),
    _build_obfuscated_phrase_pattern("con", "cax"),
    _build_obfuscated_phrase_pattern("con", "cko"),
    _build_obfuscated_phrase_pattern("cho", "de"),
]

# Khởi tạo các mẫu Regex cho từng từ tục tĩu bị giấu (Obfuscated words)
_OBFUSCATED_WORD_REGEX = [_build_obfuscated_word_pattern(term) for term in _OBFUSCATED_TERMS]


def normalize_vietnamese_text(text: str | None) -> str:
    """
    Hàm chuẩn hóa văn bản tiếng Việt cơ bản cho việc khớp quy tắc kiểm duyệt:
    - Chuyển thành chữ thường (lowercase)
    - Ánh xạ Leetspeak (@->$ , 0->o, v.v.)
    - Bóc tách và loại bỏ dấu thanh tiếng Việt Unicode (diacritics removal)
    - Thay thế chữ 'đ' thành 'd'
    - Giữ nguyên ranh giới các từ (không gộp toàn bộ thành chuỗi liền)
    """
    base = (text or "").strip().lower()
    if not base:
        return ""
    base = base.translate(_LEET_MAP).replace("đ", "d")
    decomposed = unicodedata.normalize("NFKD", base)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_marks)


# Bảng ánh xạ chuyển đổi chữ số bằng chữ (Anh & Việt) sang ký tự số tương ứng
_DIGIT_WORDS_MAP = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "khong": "0", "mot": "1", "hai": "2", "ba": "3", "bon": "4",
    "nam": "5", "sau": "6", "bay": "7", "tam": "8", "chin": "9",
    "k0": "0"
}


def clean_and_normalize_text(text: str | None) -> str:
    """
    Pipeline chuẩn hóa văn bản tiếng Việt nâng cao chuyên sâu (Dùng cho cả bài viết, bình luận & OCR):
    1. Chuyển chữ thường và làm sạch các biểu tượng teencode Telex/VNI (vd: ne^u -> neu, muo^'n -> muon).
    2. Bảo vệ các từ Tiếng Anh chứa 'ow' (vd: window, yellow, flower, show, shadow...) không bị xóa nhầm.
    3. Loại bỏ ký tự đánh dấu thanh Teencode VNI/Telex ở đuôi từ (vd: cko's -> cko, ha`ng -> hang).
    4. Bóc tách dấu thanh Unicode combining diacritics.
    5. Chuyển đổi các chữ số viết bằng chữ ("không chín" -> "09").
    6. Gộp các khoảng trắng giữa các chữ số hoặc từ bị cố ý gõ rời rạc (vd: "0 9 1 2" -> "0912", "g un" -> "gun").
    
    Returns:
        Văn bản đã được chuẩn hóa hoàn toàn ở dạng chữ cái không dấu và chữ số gọn gàng.
    """
    if not text:
        return ""

    val = text.lower().strip()

    # Bước 1: Xử lý các ký tự Teencode / VNI gõ kèm (e^ -> e, o^ -> o, a^ -> a, u* -> u, v.v.)
    val = val.replace("e^", "e").replace("o^", "o").replace("a^", "a")
    val = val.replace("o+", "o").replace("u+", "u").replace("a+", "a")
    val = val.replace("o*", "o").replace("u*", "u").replace("a*", "a")
    
    # Danh sách các từ tiếng Anh có đuôi 'ow' cần được miễn trừ không xóa đuôi
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

    # Loại bỏ các dấu thanh kiểu VNI / Telex (vd: 's, 'f, 'r, 'x, 'j, '1, '2...)
    val = re.sub(r"['``]([sfrxj1-589])\b", "", val)
    val = re.sub(r"['``](?=\s|$)", "", val)
    val = re.sub(r"(?<=[a-zA-Z])['``](?=[a-zA-Z])", "", val)

    # Bước 2: Bóc tách và loại bỏ dấu thanh Unicode
    decomposed = unicodedata.normalize("NFKD", val)
    val = "".join(ch for ch in decomposed if not unicodedata.combining(ch))

    # Bước 3: Làm sạch chữ số phụ đính kèm đuôi VNI (1-5, 8-9)
    words = val.split()
    cleaned_words = []
    for word in words:
        if word.isdigit():
            cleaned_word = word
        else:
            w_clean = re.sub(r"(?<=[a-zA-Z])[1-589]\b", "", word)
            cleaned_chars = []
            for ch in w_clean:
                if ch.isalnum():
                    cleaned_chars.append(ch)
            cleaned_word = "".join(cleaned_chars)
        if cleaned_word:
            cleaned_words.append(cleaned_word)

    normalized_text = " ".join(cleaned_words)

    # Bước 4: Chuyển các từ viết bằng chữ số sang dạng ký tự số
    words = normalized_text.split()
    mapped_words = []
    for w in words:
        if w in _DIGIT_WORDS_MAP:
            mapped_words.append(_DIGIT_WORDS_MAP[w])
        else:
            mapped_words.append(w)
    normalized_text = " ".join(mapped_words)

    # Bước 5: Gộp các khoảng trắng thừa giữa các ký tự số đứng liền kề
    normalized_text = re.sub(r"(?<=\d)\s+(?=\d)", "", normalized_text)

    # Gộp các từ bị gõ cách rời rạc phổ biến (vd: "g un" -> "gun", "s d t" -> "sdt")
    normalized_text = re.sub(r"\bg\s+un\b", "gun", normalized_text)
    normalized_text = re.sub(r"\bs\s+d\s+t\b", "sdt", normalized_text)

    # Vòng lặp gộp các ký tự đơn lẻ đứng cạnh nhau (vd: "c a k" -> "cak")
    prev_text = ""
    while normalized_text != prev_text:
        prev_text = normalized_text
        normalized_text = re.sub(r"\b([a-hj-np-z0-9])\s+([a-hj-np-z0-9])\b", r"\1\2", normalized_text)

    return re.sub(r"\s+", " ", normalized_text).strip()


def has_hard_profanity(text: str | None) -> bool:
    """
    Hàm phát hiện từ tục tĩu / chửi thề cực đoan (Hard Profanity Detector):
    Thực hiện qua 4 bước kiểm tra độc lập để tránh bị bắt nhầm các từ chứa substring hợp lệ:
    1. Kiểm tra trực tiếp các từ chửi thề tiếng Việt nguyên bản có dấu.
    2. Kiểm tra các biến thể không dấu và teencode sau khi chuẩn hóa.
    3. Kiểm tra các cụm từ chửi thề bị cố tình chèn khoảng trắng/ký tự rác giữa các từ.
    4. Kiểm tra từng từ chửi thề bị cố tình chèn khoảng trắng/ký tự rác giữa các chữ cái.
    """
    if not text:
        return False

    # 1. Kiểm tra các từ chửi thề có dấu trong văn bản gốc
    lower_text = text.lower()
    if any(word in lower_text for word in _RAW_HARD_PROFANITY_WORDS):
        return True
        
    # 2. Kiểm tra các mẫu Regex biến thể không dấu/teencode
    normalized = normalize_vietnamese_text(text)
    if any(pattern.search(normalized) for pattern in _HARD_PROFANITY_REGEX):
        return True
        
    # 3. Kiểm tra các cụm từ bị chèn ký tự phân cách (Obfuscated phrases)
    if any(pattern.search(normalized) for pattern in _OBFUSCATED_PHRASE_REGEX):
        return True

    # 4. Kiểm tra từng từ bị chèn ký tự phân cách (Obfuscated words)
    if any(pattern.search(normalized) for pattern in _OBFUSCATED_WORD_REGEX):
        return True

    return False


def split_graphemes(text: str) -> list[str]:
    """
    Phân tách chuỗi văn bản thành danh sách các cụm ký tự đồ họa hiển thị (Grapheme Clusters).
    Giúp xử lý chính xác các ký tự phức hợp như Emoji có màu da, Emoji ghép nối (ZWJ), dấu thanh kết hợp.
    """
    graphemes = []
    if not text:
        return graphemes
    
    current_grapheme = []
    for ch in text:
        code = ord(ch)
        if (0xFE00 <= code <= 0xFE0F or
            0x1F3FB <= code <= 0x1F3FF or
            code == 0x200D or
            code == 0x20E3 or
            unicodedata.combining(ch)):
            if current_grapheme:
                current_grapheme.append(ch)
            else:
                current_grapheme = [ch]
        else:
            if current_grapheme and current_grapheme[-1] == '\u200d':
                current_grapheme.append(ch)
            else:
                if current_grapheme:
                    graphemes.append("".join(current_grapheme))
                current_grapheme = [ch]
                
    if current_grapheme:
        graphemes.append("".join(current_grapheme))
        
    return graphemes


def is_emoji_grapheme(g: str) -> bool:
    """Kiểm tra xem cụm Grapheme g có đại diện cho 1 ký tự Emoji hay không."""
    if not g:
        return False
    code = ord(g[0])
    if (0x1F300 <= code <= 0x1F9FF or
        0x1FA00 <= code <= 0x1FAFF or
        0x2600 <= code <= 0x27BF or
        0x1F000 <= code <= 0x1F0FF or
        0x1F100 <= code <= 0x1F2FF or
        0x1F680 <= code <= 0x1F6FF):
        return True
    cat = unicodedata.category(g[0])
    return cat in ("So", "Cn") and code > 0x7F


def analyze_and_sanitize_text(text: str) -> tuple[str, bool, str | None]:
    """
    Phân tích và làm sạch văn bản đánh giá / bình luận để phát hiện hành vi Spam Emoji và Ký tự:
    
    Quy tắc kiểm tra:
    -----------------
    - Nếu 1 ký tự hoặc emoji lặp lại liên tiếp quá 5 lần -> Từ chối (rejected=True) và gắn cờ spam.
    - Nếu chuỗi ký tự lặp lại quá 3 lần -> Tự động nén/thu gọn về tối đa 3 lần lặp (Sanitization).
    - Nếu tổng số lượng emoji trong toàn bài vượt quá 10 emoji -> Từ chối vì vi phạm spam emoji.
    
    Returns:
        tuple(normalized_text, rejected_status, reason_if_rejected)
    """
    graphemes = split_graphemes(text)
    if not graphemes:
        return text, False, None
    
    max_consecutive_allowed = 5  # Giới hạn lặp liên tiếp tối đa cho phép
    max_consecutive_for_normalization = 3  # Giới hạn thu gọn nén chuỗi lặp
    
    normalized_graphemes = []
    current_g = ""
    current_count = 0
    
    for g in graphemes:
        if g == current_g:
            current_count += 1
            # Chặn ngay nếu lặp lại quá 5 lần
            if current_count > max_consecutive_allowed:
                is_emoji = is_emoji_grapheme(g)
                spam_type = "emoji" if is_emoji else "character"
                return text, True, f"Excessive consecutive {spam_type} repetition (more than {max_consecutive_allowed} times)"
            
            if current_count <= max_consecutive_for_normalization:
                normalized_graphemes.append(g)
        else:
            current_g = g
            current_count = 1
            normalized_graphemes.append(g)
            
    total_emojis = sum(1 for g in normalized_graphemes if is_emoji_grapheme(g))
    max_total_emojis = 10  # Giới hạn tổng số lượng emoji tối đa trong 1 bình luận
    if total_emojis > max_total_emojis:
        return text, True, f"Review contains excessive emoji spam (more than {max_total_emojis} emojis)"
        
    return "".join(normalized_graphemes), False, None


