"""
app/ai/engines/content_analyzer.py
-----------------------------------
Consolidates all rule-based checks, local heuristic classification,
intent analysis, and safety validations for reviews, blog comments, and articles.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.utils.text_utils import (
    has_hard_profanity,
    clean_and_normalize_text,
    normalize_vietnamese_text,
    analyze_and_sanitize_text,
)

# ──────────────────────────────────────────────────────────────────────────────
# Patterns & Constants
# ──────────────────────────────────────────────────────────────────────────────

_URL_PATTERN = re.compile(
    r"https?://"
    r"|www\."
    r"|bit\.ly"
    r"|tinyurl\.com",
    re.IGNORECASE,
)

_EMAIL_PATTERN = re.compile(
    r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b"
    r"|\b[a-z0-9._%+-]+(?:\s*(?:dot|\.|\[dot\]|\(dot\))\s*[a-z0-9._%+-]+)*\s*(?:at|@|\[at\]|\(at\))\s*[a-z0-9.-]+\s*(?:dot|\.|\[dot\]|\(dot\))\s*[a-z]{2,}\b",
    re.IGNORECASE,
)

_VN_PHONE_PATTERN = re.compile(
    r"(?<!\d|\w)"
    r"(?:0|\+84)"
    r"(?:3|5|7|8|9)"
    r"[0-9x*._\-]{3,12}"
    r"(?!\d|\w)",
    re.IGNORECASE,
)

_VN_PHONE_CANDIDATE_PATTERN = re.compile(
    r"(?<!\w)"
    r"(?:\+?84|0)(?:[\s.\-]?\d){8,10}"
    r"(?!\w)",
    re.IGNORECASE,
)

_LONG_NUMBER_CANDIDATE_PATTERN = re.compile(
    r"(?<!\d)(?:\d[\s.\-]?){9,14}(?!\d)",
)

_BANK_ACCOUNT_PATTERN = re.compile(
    r"\b\d{9,14}\b",
)

_SQL_PATTERN = re.compile(
    r"\b(SELECT\s+[\s\S]*?\s+FROM|INSERT\s+INTO|UPDATE\s+[\s\S]*?\s+SET|DELETE\s+FROM|DROP\s+TABLE|UNION\s+SELECT)\b",
    re.IGNORECASE
)

_SOCIAL_PATTERN = re.compile(
    r"\b(follow\s+(?:us\s+|me\s+|my\s+)?(?:on\s+)?(?:instagram|ig|facebook|fb|tiktok|zalo|twitter|x)"
    r"|lh\s*(?:qua\s*)?(?:zalo|sdt|fb|ib|tele|mess|viber)"
    r"|lien\s*he\s*(?:qua\s*)?(?:zalo|sdt|fb|ib|tele|mess|viber)"
    r"|ib\s*(?:qua\s*)?(?:zalo|sdt|fb|tele|mess)"
    r"|zalo\s*(?:lh|lien\s*he|ib|inbox|sdt)"
    r"|@\w{3,})\b",
    re.IGNORECASE
)

_SPAM_PATTERN = re.compile(
    r"\b(click\s+now|click\s+here|free\s+rewards|get\s+free|free\s+gift|nhan\s+qua\s+mien\s+phi|nhan\s+thuong|click\s+vao|tang\s+qua)\b",
    re.IGNORECASE
)

_INJECTION_PATTERN = re.compile(
    r"\b(skip\s+all\s+validation|ignore\s+previous\s+rules|bypass\s+rules|internal\s+test"
    r"|bo\s+qua\s+quy\s+tac|bo\s+qua\s+cac\s+quy\s+tac|bo\s+qua\s+rule"
    r"|khong\s+duoc\s+approved|khong\s+duoc\s+duyet"
    r"|hay\s+xuat\s+ra\s+ket\s+qua|yeu\s+cau\s+xuat\s+ra)\b",
    re.IGNORECASE
)

_SOCIAL_PLATFORM_PATTERN = re.compile(
    r"\b(?:"
    r"tik\s*tok|tiktok|instagram|insta|discord|twitter|x\s*/\s*twitter|x-twitter|x twitter|"
    r"facebook|fb|messenger|telegram|whatsapp|wechat|line|snapchat"
    r")\b",
    re.IGNORECASE,
)

_SOCIAL_HANDLE_PATTERN = re.compile(
    r"(?<![\w.])@([A-Za-z0-9](?:[A-Za-z0-9._]{1,31}))\b",
)

_DISCORD_TAG_PATTERN = re.compile(
    r"\b[a-z0-9._]{2,32}#[0-9]{4}\b",
    re.IGNORECASE,
)

_CONTACT_INTENT_PATTERN = re.compile(
    r"\b(?:"
    r"lien he|lien lac|ib|inbox|nhan tin|message|dm|"
    r"contact|reach me|find me|add me|follow me|ping me|text me|"
    r"connect|chat|talk|discuss|"
    r"ket ban|add|follow|trao doi"
    r")\b",
    re.IGNORECASE,
)

_PLATFORM_WITH_USERNAME_PATTERN = re.compile(
    r"\b(?:"
    r"tik\s*tok|tiktok|instagram|insta|discord|twitter|x\s*/\s*twitter|x-twitter|x twitter|"
    r"facebook|fb|messenger|telegram|whatsapp|wechat|line|snapchat"
    r")\b"
    r".{0,24}\b(?:la|is|as|username|user|nick|acc|account|id|handle)\b.{0,8}\b([a-z0-9][a-z0-9._]{2,31})\b",
    re.IGNORECASE,
)

_USERNAME_ON_PLATFORM_PATTERN = re.compile(
    r"\b([a-z0-9][a-z0-9._]{4,31})\b\s+(?:tren|on|in|via)\s+"
    r"(?:"
    r"tik\s*tok|tiktok|instagram|insta|discord|twitter|x\s*/\s*twitter|x-twitter|x twitter|"
    r"facebook|fb|messenger|telegram|whatsapp|wechat|line|snapchat"
    r")\b",
    re.IGNORECASE,
)

_NON_USERNAME_TOKENS: set[str] = {
    "instagram", "tiktok", "discord", "twitter", "facebook", "messenger",
    "telegram", "whatsapp", "trend", "video", "shop",
}

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_LETTER_PATTERN = re.compile(r"[a-z]")
_DIGIT_PATTERN = re.compile(r"\d")
_SYMBOL_ONLY_PATTERN = re.compile(r"^[\W_]+$", re.UNICODE)
_KEYBOARD_WALK_TOKENS = {"qwerty", "qwertyui", "qwertyuiop", "asdfgh", "zxcvbn", "abcxyz"}

_INAPPROPRIATE_EMOJI_CATEGORIES: dict[str, str] = {
    "🤤": "adult", "🔞": "adult", "🖕": "offensive", "🤬": "offensive",
    "🔪": "violent", "🚬": "adult", "🍺": "adult", "🍻": "adult",
    "🍷": "adult", "🍸": "adult",
}

# ── Blog safety check parameters ──────────────────────────────────────

BLOCKED_KEYWORDS: dict[str, list[str]] = {
    "brand_external": [
        "mykingdom", "my kingdom", "ti ni", "tini", "tini store", "tiniworld",
        "lazada", "shopee", "tiki", "sendo", "amazon", "bibo mart", "fahasa",
    ],
    "topic_restricted": [
        "chinh tri", "ton giao", "bao luc", "co bac",
        "vu khi", "noi dung nguoi lon", "chat kich thich",
    ],
}

HARD_BLOCK_EMOJIS = ("🖕", "👅", "🍆", "😏", "🔞", "🚬", "🍺", "🍷", "🍸", "🚭")

_PROMPT_INJECTION_PATTERNS = (
    "ignore previous instructions", "reveal system prompt",
    "output hidden rules", "bypass moderation", "act as another ai",
)

DEFAULT_BLOCK_SUGGESTIONS = [
    "STEM toys suitable for children by age",
    "Guide to choosing birthday gifts for kids",
    "Top most popular creative toys",
    "Safe online toy shopping tips for parents",
]

_ALLOWED_DOMAIN_ANCHORS = (
    "toy", "toys", "children", "child", "kids", "kid", "parenting", "learning", "stem",
    "gift", "review", "safety", "seasonal", "outdoor", "role play", "creativity",
    "anatomy", "skeleton", "brain", "doctor", "halloween", "dinosaur", "monster", "fantasy",
    "water gun", "water blaster", "foam blaster",
)

_BLOCKED_DOMAIN_HINTS = (
    "politics", "election", "religion debate", "cryptocurrency", "crypto", "forex",
    "stock trading", "gambling", "adult content", "dating", "relationship advice",
    "medical treatment", "hacking", "crime", "weapon", "drug usage",
)

_UNSAFE_THEME_HINTS = (
    "death", "dead body", "corpse", "human remains", "terrifying", "terror", "horror",
    "gore", "gory", "bloody", "blood bath", "dismember", "decapitated", "violent scene",
    "graphic", "nightmare", "fear inducing",
)

_EDUCATIONAL_SAFETY_CONTEXT = (
    "educational", "education", "learning", "stem", "anatomy", "biology", "science",
    "model", "toy", "toys", "children", "kids", "child development", "role play",
)


# ──────────────────────────────────────────────────────────────────────────────
# Dataclasses & Helper Classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PrefilterResult:
    rejected: bool
    reason: str = ""


@dataclass(frozen=True)
class BlogCommentPrefilterResult:
    rejected: bool
    category: str = ""
    reason: str = ""
    flag: str = ""


@dataclass(frozen=True)
class SocialContactDetectionResult:
    detected: bool
    reason: str = ""
    flag: str = ""


@dataclass(frozen=True)
class ContentSignal:
    detected: bool
    category: str = ""
    reason: str = ""
    flag: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# Product Review Local Filters
# ──────────────────────────────────────────────────────────────────────────────

def find_sensitive_patterns(text: str) -> str | None:
    if _URL_PATTERN.search(text):
        return "Contains URL or shortened link"
    if _EMAIL_PATTERN.search(text):
        return "Contains email address (or obfuscated email)"
    if _VN_PHONE_PATTERN.search(text):
        return "Contains Vietnamese phone number"
    if _BANK_ACCOUNT_PATTERN.search(text):
        return "Contains bank-account-like number sequence"
    if _SQL_PATTERN.search(text):
        return "Contains database query syntax (SQL)"
    if _SOCIAL_PATTERN.search(text):
        return "Contains social media contact info / self-promotion"
    if _SPAM_PATTERN.search(text):
        return "Contains advertising content / spam clickbait"
    if _INJECTION_PATTERN.search(text):
        return "Suspected moderation bypass behavior (Instruction Injection)"
    return None


def run_prefilter(comment: str) -> PrefilterResult:
    normalized, rejected, reason = analyze_and_sanitize_text(comment)
    if rejected:
        return PrefilterResult(True, reason)
    comment = normalized

    if not comment or not comment.strip():
        return PrefilterResult(True, "Empty or whitespace-only content")

    meaningful_count = sum(1 for ch in comment if ch.isalnum())
    if meaningful_count < 5:
        return PrefilterResult(True, f"Too few meaningful characters: {meaningful_count} (minimum 5)")

    if len(comment) > 10:
        char_freq: dict[str, int] = {}
        for ch in comment:
            char_freq[ch] = char_freq.get(ch, 0) + 1
        max_freq = max(char_freq.values())
        if max_freq / len(comment) > 0.70:
            return PrefilterResult(True, "Repeated character spam: more than 70% of content is the same character")

    normalized = clean_and_normalize_text(comment)
    if has_hard_profanity(comment) or has_hard_profanity(normalized):
        return PrefilterResult(True, "Contains extreme vulgar profanity (auto-blocked)")

    sensitive_reason = find_sensitive_patterns(comment)
    if not sensitive_reason:
        sensitive_reason = find_sensitive_patterns(normalized)
    if sensitive_reason:
        return PrefilterResult(True, sensitive_reason)

    return PrefilterResult(False, "")


# ──────────────────────────────────────────────────────────────────────────────
# Blog Comment Local Filters
# ──────────────────────────────────────────────────────────────────────────────

def _extract_digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _is_vn_phone_candidate(candidate: str) -> bool:
    compact = candidate.strip().replace(" ", "").replace(".", "").replace("-", "")
    if compact.startswith("+84"):
        digits = compact[3:]
    elif compact.startswith("84"):
        digits = compact[2:]
    elif compact.startswith("0"):
        digits = compact[1:]
    else:
        return False
    return len(digits) in (9, 10) and digits.isdigit()


def _contains_vn_phone(text: str) -> bool:
    for match in _VN_PHONE_CANDIDATE_PATTERN.finditer(text):
        if _is_vn_phone_candidate(match.group(0)):
            return True
    return False


def _contains_bank_account_like_number(text: str) -> bool:
    for match in _LONG_NUMBER_CANDIDATE_PATTERN.finditer(text):
        token = match.group(0)
        digits = _extract_digits(token)
        if len(digits) < 9 or len(digits) > 14:
            continue
        if _is_vn_phone_candidate(token):
            continue
        return True
    return False


def _contains_address_like_personal_info(text: str) -> bool:
    segments = [segment.strip() for segment in re.split(r"[,\n]", text) if segment.strip()]
    if len(segments) < 2:
        return False
    snippet = ", ".join(segments[:4])
    alpha_count = sum(1 for ch in snippet if ch.isalpha())
    digit_groups = re.findall(r"\d{1,6}", snippet)
    word_count = len([token for token in re.split(r"\s+", snippet.strip()) if token])
    has_numbered_segment = any(
        re.search(r"[A-Za-z]", segment) and re.search(r"\d{1,6}", segment)
        for segment in segments
    )
    has_geographic_depth = len(digit_groups) >= 2 or any(len(group) >= 5 for group in digit_groups)
    return has_numbered_segment and alpha_count >= 12 and word_count >= 5 and has_geographic_depth


def detect_social_contact_info(comment: str) -> SocialContactDetectionResult:
    if not comment or not comment.strip():
        return SocialContactDetectionResult(detected=False)
    normalized = normalize_vietnamese_text(comment)
    if not normalized:
        return SocialContactDetectionResult(detected=False)

    if _SOCIAL_HANDLE_PATTERN.search(comment):
        return SocialContactDetectionResult(
            detected=True, reason="Contains social media handle or username", flag="rule_social_handle_detected"
        )
    if _DISCORD_TAG_PATTERN.search(comment) and "discord" in normalized:
        return SocialContactDetectionResult(
            detected=True, reason="Contains Discord tag for external contact", flag="rule_discord_tag_detected"
        )

    platform_mentioned = _SOCIAL_PLATFORM_PATTERN.search(normalized) is not None
    contact_intent = _CONTACT_INTENT_PATTERN.search(normalized) is not None
    has_social_channel_phrase = (
        "mang xa hoi" in normalized or "ket noi ben ngoai" in normalized
        or "social media" in normalized or "outside the platform" in normalized
        or "off platform" in normalized
    )
    if (platform_mentioned and contact_intent) or (has_social_channel_phrase and contact_intent):
        return SocialContactDetectionResult(
            detected=True, reason="Encourages contact via social media", flag="rule_social_contact_intent_detected"
        )

    for match in _PLATFORM_WITH_USERNAME_PATTERN.finditer(normalized):
        username = match.group(1)
        if _looks_like_username(username):
            return SocialContactDetectionResult(
                detected=True, reason="Contains social username on platform", flag="rule_social_username_detected"
            )
    for match in _USERNAME_ON_PLATFORM_PATTERN.finditer(normalized):
        username = match.group(1)
        if _looks_like_username(username):
            return SocialContactDetectionResult(
                detected=True, reason="Contains likely social account mention", flag="rule_social_username_detected"
            )
    return SocialContactDetectionResult(detected=False)


def _looks_like_username(token: str) -> bool:
    lowered = token.strip().lower()
    if not lowered or lowered.isdigit() or lowered in _NON_USERNAME_TOKENS:
        return False
    return "_" in lowered or "." in lowered or any(ch.isdigit() for ch in lowered) or len(lowered) >= 9


def detect_meaningless_content(comment: str) -> ContentSignal:
    normalized = normalize_vietnamese_text(comment)
    compact = re.sub(r"\s+", "", normalized)
    tokens = _TOKEN_PATTERN.findall(normalized)
    if not compact:
        return ContentSignal(detected=False)

    if _SYMBOL_ONLY_PATTERN.fullmatch(compact) and len(compact) >= 4:
        return ContentSignal(
            detected=True, category="spam", reason="Symbol-only meaningless content detected", flag="rule_symbol_only_spam"
        )
    if tokens and _is_repeated_meaningless_phrase(tokens):
        return ContentSignal(
            detected=True, category="spam", reason="Repeated meaningless phrase detected", flag="rule_repeated_phrase_spam"
        )
    if len(tokens) == 1:
        token = tokens[0]
        if _is_meaningless_single_token(token):
            return ContentSignal(
                detected=True, category="spam", reason="Meaningless token pattern detected", flag="rule_meaningless_token_spam"
            )
    if _is_multi_token_gibberish(tokens):
        return ContentSignal(
            detected=True, category="spam", reason="Multi-token gibberish content detected", flag="rule_multi_token_gibberish_spam"
        )
    return ContentSignal(detected=False)


def _is_repeated_meaningless_phrase(tokens: list[str]) -> bool:
    if len(tokens) < 3:
        return False
    unique_tokens = set(tokens)
    if len(unique_tokens) == 1 and len(next(iter(unique_tokens))) <= 8:
        return True
    most_common_count = max(tokens.count(token) for token in unique_tokens)
    return (
        len(tokens) >= 4 and len(unique_tokens) <= 2 and most_common_count / len(tokens) >= 0.75
        and all(len(token) <= 8 for token in unique_tokens)
    )


def _is_meaningless_single_token(token: str) -> bool:
    if len(token) < 4:
        return False
    if token in _KEYBOARD_WALK_TOKENS:
        return True
    if len(set(token)) == 1 and len(token) >= 6:
        return True
    if _is_repeated_pattern(token):
        return True
    if _DIGIT_PATTERN.fullmatch(token) and len(token) >= 6:
        return _is_numeric_noise(token)
    if _LETTER_PATTERN.fullmatch(token):
        return _is_alpha_noise(token)
    return False


def _is_repeated_pattern(token: str) -> bool:
    if len(token) < 6:
        return False
    max_unit_length = min(4, len(token) // 2)
    for unit_length in range(1, max_unit_length + 1):
        if len(token) % unit_length != 0:
            continue
        unit = token[:unit_length]
        if unit * (len(token) // unit_length) == token and len(token) // unit_length >= 3:
            return True
    return False


def _is_numeric_noise(token: str) -> bool:
    if len(set(token)) <= 2:
        return True
    return _is_repeated_pattern(token)


def _is_alpha_noise(token: str) -> bool:
    if len(set(token)) <= 2:
        return True
    vowel_count = sum(1 for ch in token if ch in "aeiouy")
    vowel_ratio = vowel_count / len(token)
    if len(token) >= 8 and vowel_ratio < 0.2 and len(set(token)) <= 5:
        return True
    return False


def _is_multi_token_gibberish(tokens: list[str]) -> bool:
    alpha_tokens = [token for token in tokens if token.isalpha()]
    medium_tokens = [token for token in alpha_tokens if len(token) >= 4]
    long_gibberish_tokens = [token for token in medium_tokens if _looks_like_gibberish_alpha_token(token)]
    if len(long_gibberish_tokens) < 2:
        return False
    if len(medium_tokens) < 2:
        return False
    total_alpha_chars = sum(len(token) for token in alpha_tokens)
    gibberish_ratio = len(long_gibberish_tokens) / len(medium_tokens)
    return total_alpha_chars >= 12 and gibberish_ratio >= 0.6


def _looks_like_gibberish_alpha_token(token: str) -> bool:
    if len(token) < 6:
        return False
    vowel_count = sum(1 for ch in token if ch in "aeiouy")
    vowel_ratio = vowel_count / len(token)
    consonant_cluster = _longest_consonant_cluster(token)
    if consonant_cluster >= 5:
        return True
    if consonant_cluster >= 4 and vowel_ratio <= 0.30:
        return True
    if vowel_count == 0 and len(token) >= 6:
        return True
    return False


def _longest_consonant_cluster(token: str) -> int:
    longest = 0
    current = 0
    for ch in token:
        if ch in "aeiouy":
            current = 0
            continue
        current += 1
        if current > longest:
            longest = current
    return longest


def detect_inappropriate_emoji_usage(comment: str) -> ContentSignal:
    blocked_hits = [(emoji, _INAPPROPRIATE_EMOJI_CATEGORIES[emoji]) for emoji in comment if emoji in _INAPPROPRIATE_EMOJI_CATEGORIES]
    if not blocked_hits:
        return ContentSignal(detected=False)

    stripped = comment
    for emoji in _INAPPROPRIATE_EMOJI_CATEGORIES:
        stripped = stripped.replace(emoji, " ")

    normalized_text = normalize_vietnamese_text(stripped)
    tokens = _TOKEN_PATTERN.findall(normalized_text)
    meaningful_text_length = sum(len(token) for token in tokens)
    blocked_count = len(blocked_hits)
    non_space_count = sum(1 for ch in comment if not ch.isspace())

    has_clear_neutral_context = len(tokens) >= 4 or meaningful_text_length >= 16
    emoji_dominant = (
        not tokens
        or blocked_count >= max(2, len(tokens))
        or blocked_count * 3 >= max(1, non_space_count)
    )
    if has_clear_neutral_context or not emoji_dominant:
        return ContentSignal(detected=False)

    def _pick_emoji_category(cats: list[str]) -> str:
        if "violent" in cats:
            return "violent"
        if "offensive" in cats:
            return "offensive"
        return "adult"

    category = _pick_emoji_category([item[1] for item in blocked_hits])
    return ContentSignal(
        detected=True, category=category,
        reason="Contextually inappropriate emoji-only or emoji-dominant content detected",
        flag="rule_inappropriate_emoji_context",
    )


def run_blog_comment_prefilter(comment: str) -> BlogCommentPrefilterResult:
    normalized, rejected, reason = analyze_and_sanitize_text(comment)
    if rejected:
        return BlogCommentPrefilterResult(
            rejected=True, category="spam", reason=reason, flag="rule_spam_detected"
        )
    comment = normalized

    if not comment or not comment.strip():
        return BlogCommentPrefilterResult(
            rejected=True, category="spam", reason="Empty or whitespace-only content", flag="rule_empty_content"
        )

    if len(comment) > 10:
        char_freq: dict[str, int] = {}
        for ch in comment:
            char_freq[ch] = char_freq.get(ch, 0) + 1
        max_freq = max(char_freq.values())
        if max_freq / len(comment) > 0.70:
            return BlogCommentPrefilterResult(
                rejected=True, category="spam", reason="Repeated-character spam pattern detected", flag="rule_repeated_char_spam"
            )

    meaningless_signal = detect_meaningless_content(comment)
    if meaningless_signal.detected:
        return BlogCommentPrefilterResult(
            rejected=True, category=meaningless_signal.category, reason=meaningless_signal.reason, flag=meaningless_signal.flag
        )

    inappropriate_emoji_signal = detect_inappropriate_emoji_usage(comment)
    if inappropriate_emoji_signal.detected:
        return BlogCommentPrefilterResult(
            rejected=True, category=inappropriate_emoji_signal.category, reason=inappropriate_emoji_signal.reason, flag=inappropriate_emoji_signal.flag
        )

    if _URL_PATTERN.search(comment):
        return BlogCommentPrefilterResult(
            rejected=True, category="spam", reason="Contains URL or shortened link", flag="rule_url_detected"
        )

    social_contact = detect_social_contact_info(comment)
    if social_contact.detected:
        return BlogCommentPrefilterResult(
            rejected=True, category="spam", reason=social_contact.reason, flag=social_contact.flag
        )

    if _EMAIL_PATTERN.search(comment):
        return BlogCommentPrefilterResult(
            rejected=True, category="privacy", reason="Contains an email address", flag="rule_email_detected"
        )
    if _contains_vn_phone(comment):
         return BlogCommentPrefilterResult(
            rejected=True, category="privacy", reason="Contains a Vietnamese phone number", flag="rule_phone_detected"
        )
    if _contains_bank_account_like_number(comment):
        return BlogCommentPrefilterResult(
            rejected=True, category="privacy", reason="Contains bank-account-like number sequence", flag="rule_bank_account_detected"
        )
    if _contains_address_like_personal_info(comment):
        return BlogCommentPrefilterResult(
            rejected=True, category="privacy", reason="Contains detailed personal address information", flag="rule_address_detected"
        )
    if has_hard_profanity(comment):
        return BlogCommentPrefilterResult(
            rejected=True, category="offensive", reason="Contains severe profanity", flag="rule_hard_profanity_reject"
        )

    return BlogCommentPrefilterResult(rejected=False)


# ──────────────────────────────────────────────────────────────────────────────
# Blog Generation Local Safety Filters
# ──────────────────────────────────────────────────────────────────────────────

def _has_vietnamese_diacritic(value: str) -> bool:
    return bool(re.search(r"[ăâđêôơưáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]", (value or "").lower()))


def _normalize_for_check(value: str, *, strip_diacritic: bool = True) -> str:
    lowered = (value or "").lower()
    if strip_diacritic:
        normalized = "".join(
            ch for ch in unicodedata.normalize("NFKD", lowered) if not unicodedata.combining(ch)
        )
        alpha_num_space = re.sub(r"[^a-z0-9\s]", " ", normalized)
    else:
        alpha_num_space = re.sub(r"[^\w\s]", " ", lowered, flags=re.UNICODE)
    return re.sub(r"\s+", " ", alpha_num_space).strip()


def _build_user_context(title: str, prompt_structure: str) -> str:
    return f"{title.strip()}\n{prompt_structure.strip()}".strip()


def _contains_keyword(normalized_text: str, keyword: str) -> bool:
    normalized_kw = _normalize_for_check(keyword, strip_diacritic=True)
    if not normalized_kw:
        return False
    if len(normalized_kw) < 5:
        return re.search(rf"\b{re.escape(normalized_kw)}\b", normalized_text, flags=re.IGNORECASE) is not None
    return f" {normalized_kw} " in f" {normalized_text} "


def _detect_external_brand(title: str, prompt_structure: str) -> str | None:
    normalized = _normalize_for_check(_build_user_context(title, prompt_structure), strip_diacritic=True)
    for keyword in BLOCKED_KEYWORDS["brand_external"]:
        if _contains_keyword(normalized, keyword):
            return keyword
    return None


def _check_hard_block_emoji(title: str, prompt_structure: str) -> str | None:
    context = _build_user_context(title, prompt_structure)
    for emoji in HARD_BLOCK_EMOJIS:
        if emoji in context:
            return emoji
    return None


def _detect_prompt_injection(title: str, prompt_structure: str) -> str | None:
    normalized = _normalize_for_check(_build_user_context(title, prompt_structure), strip_diacritic=True)
    for phrase in _PROMPT_INJECTION_PATTERNS:
        if phrase in normalized:
            return phrase
    return None


def _detect_contextual_unsafe_theme(title: str, prompt_structure: str) -> str | None:
    normalized = _normalize_for_check(_build_user_context(title, prompt_structure), strip_diacritic=True)
    unsafe_hits = [hint for hint in _UNSAFE_THEME_HINTS if hint in normalized]
    if not unsafe_hits:
        return None
    edu_hits = [hint for hint in _EDUCATIONAL_SAFETY_CONTEXT if hint in normalized]
    graphic_only_hits = [hint for hint in unsafe_hits if hint in {"human remains", "gore", "gory", "dismember", "decapitated", "graphic"}]
    if graphic_only_hits:
        return graphic_only_hits[0]
    if len(unsafe_hits) >= 2 and len(edu_hits) == 0:
        return unsafe_hits[0]
    if len(unsafe_hits) >= 3 and len(edu_hits) <= 1:
        return unsafe_hits[0]
    return None


def _detect_unsafe_content(text: str) -> str | None:
    if has_hard_profanity(text):
        return "hard_profanity"
    is_vietnamese = _has_vietnamese_diacritic(text)
    normalized = _normalize_for_check(text, strip_diacritic=not is_vietnamese)
    tokenized = f" {normalized} "
    
    _SHORT_UNSAFE_TOKENS = (" dm ", " dmm ", " dcm ", " vcl ", " clm ", " clmm ", " dit ", " deo ", " duma ", " dume ")
    for short_token in _SHORT_UNSAFE_TOKENS:
        if short_token in tokenized:
            return short_token.strip()

    _UNSAFE_CONTENT_PATTERNS = [
        re.compile(r"\bfuck\b", re.IGNORECASE),
        re.compile(r"\bshit\b", re.IGNORECASE),
        re.compile(r"\bbitch\b", re.IGNORECASE),
        re.compile(r"\basshole\b", re.IGNORECASE),
        re.compile(r"\bbastard\b", re.IGNORECASE),
        re.compile(r"\bdick\b", re.IGNORECASE),
        re.compile(r"\bpussy\b", re.IGNORECASE),
        re.compile(r"\bkill\s+yourself\b", re.IGNORECASE),
        re.compile(r"\bgo\s+die\b", re.IGNORECASE),
        re.compile(r"\bditme\b", re.IGNORECASE),
        re.compile(r"\bduma\b", re.IGNORECASE),
        re.compile(r"\bdume\b", re.IGNORECASE),
        re.compile(r"\bcon\s*di\b", re.IGNORECASE),
        re.compile(r"\bcon\s*me\b", re.IGNORECASE),
    ]
    for pattern in _UNSAFE_CONTENT_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return match.group(0)
    return None


def _build_contextual_fallback_suggestions(title: str, content: str) -> list[str]:
    combined = _normalize_for_check(f"{title} {content}")
    if any(token in combined for token in ["review", "danh gia", "so sanh"]):
        return [
            "Discover Children's Toy Store - an online children's toy platform for modern families",
            "Review of top best-selling toys at Children's Toy Store by age group",
            "Compare educational toys to help children develop thinking and creativity",
            "Safe online toy shopping tips for parents with young kids",
        ]
    if any(token in combined for token in ["mua", "buy", "gia", "price", "khuyen mai", "voucher"]):
        return [
            "Guide to buying toys at Children's Toy Store quickly and safely",
            "Top recommended products to buy at Children's Toy Store for kids by age",
            "Tips for choosing budget-friendly yet effective educational toys for children",
            "Smart online toy shopping tips for busy parents",
        ]
    return [
        "Discover Children's Toy Store and features supporting toy purchases for families",
        "Recommended toys at Children's Toy Store based on child development needs",
        "Top play-and-learn activities to help kids develop comprehensive skills at home",
        "Tips for choosing age-appropriate toys for a worry-free shopping experience",
    ]


def safety_check(title: str, prompt_structure: str) -> dict[str, str | list[str]] | None:
    context = _build_user_context(title, prompt_structure)
    injection = _detect_prompt_injection(title, prompt_structure)
    if injection:
        return {
            "status": "blocked",
            "violation_type": "unsafe_content",
            "violated_keyword": injection,
            "reason": "prompt_injection",
            "suggestions": DEFAULT_BLOCK_SUGGESTIONS[:4],
        }

    external_brand = _detect_external_brand(title, prompt_structure)
    if external_brand:
        return {
            "status": "blocked",
            "violation_type": "brand_external",
            "violated_keyword": external_brand,
            "reason": "external_brand",
            "suggestions": _build_contextual_fallback_suggestions(title, prompt_structure)[:4],
        }

    contextual_unsafe = _detect_contextual_unsafe_theme(title, prompt_structure)
    if contextual_unsafe:
        return {
            "status": "blocked",
            "violation_type": "unsafe_content",
            "violated_keyword": contextual_unsafe,
            "reason": "unsafe_content",
            "suggestions": DEFAULT_BLOCK_SUGGESTIONS[:4],
        }

    unsafe_match = _detect_unsafe_content(context)
    if unsafe_match:
        return {
            "status": "blocked",
            "violation_type": "unsafe_content",
            "violated_keyword": unsafe_match,
            "reason": "unsafe_content",
            "suggestions": DEFAULT_BLOCK_SUGGESTIONS[:4],
        }
    return None


def _build_source_content_warning(source_content: str | None) -> str | None:
    if not source_content:
        return None
    source_violation = _detect_unsafe_content(source_content)
    if source_violation:
        return (
            "Source content contains sensitive terms; system continues generation for Improve mode "
            f"and bypasses block from sourceContent (matched: {source_violation})."
        )
    return None


def classify_intent(
    *,
    title: str,
    description: str | None,
    prompt_structure: str,
    category_id: int,
) -> dict[str, str | bool | float]:
    combined = _build_user_context(title, prompt_structure)
    normalized = _normalize_for_check(combined, strip_diacritic=True)
    if not normalized:
        return {
            "is_relevant": False,
            "confidence": 0.95,
            "reason": "off_topic",
            "suggestion": "Please add context about toys, parenting, or child development.",
            "decision": "block",
            "source": "heuristic",
        }

    anchor_hits = sum(1 for anchor in _ALLOWED_DOMAIN_ANCHORS if anchor in normalized)
    off_topic_hits = sum(1 for hint in _BLOCKED_DOMAIN_HINTS if hint in normalized)
    token_count = max(1, len(normalized.split()))
    relevance_score = min(1.0, ((anchor_hits * 1.3) + (0.8 if category_id > 0 else 0.0)) / token_count)

    if off_topic_hits > 0 and anchor_hits == 0:
        return {
            "is_relevant": False,
            "confidence": 0.9,
            "reason": "off_topic",
            "suggestion": "Please shift the prompt to toy store topics, such as choosing age-appropriate toys or toy safety.",
            "decision": "block",
            "source": "heuristic",
        }

    _INTENT_PASS_CONFIDENCE = 0.55
    if relevance_score >= _INTENT_PASS_CONFIDENCE:
        return {
            "is_relevant": True,
            "confidence": relevance_score,
            "reason": "",
            "suggestion": "",
            "decision": "pass",
            "source": "heuristic",
        }

    return {
        "is_relevant": True,
        "confidence": relevance_score,
        "reason": "Intent not fully clear, allowed to proceed to avoid false blocking.",
        "suggestion": "",
        "decision": "review",
        "source": "heuristic",
    }


def output_validation(content_html: str) -> tuple[str, str]:
    cleaned = content_html
    for emoji in HARD_BLOCK_EMOJIS:
        cleaned = cleaned.replace(emoji, "")

    unsafe_marker = _detect_unsafe_content(cleaned)
    if unsafe_marker:
        return "reject", unsafe_marker

    normalized = _normalize_for_check(cleaned, strip_diacritic=True)
    if any(marker in normalized for marker in ("hate", "racist", "ethnic cleansing")):
        return "reject", "hate_content"

    return "pass", cleaned
