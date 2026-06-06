from __future__ import annotations

import re
from dataclasses import dataclass

from app.utils.text_utils import normalize_vietnamese_text

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_LETTER_PATTERN = re.compile(r"[a-z]")
_DIGIT_PATTERN = re.compile(r"\d")
_SYMBOL_ONLY_PATTERN = re.compile(r"^[\W_]+$", re.UNICODE)
_KEYBOARD_WALK_TOKENS = {
    "qwerty",
    "qwertyui",
    "qwertyuiop",
    "asdfgh",
    "zxcvbn",
    "abcxyz",
}

_INAPPROPRIATE_EMOJI_CATEGORIES: dict[str, str] = {
    "🤤": "adult",
    "🔞": "adult",
    "🖕": "offensive",
    "🤬": "offensive",
    "🔪": "violent",
    "🚬": "adult",
    "🍺": "adult",
    "🍻": "adult",
    "🍷": "adult",
    "🍸": "adult",
}


@dataclass(frozen=True)
class ContentSignal:
    detected: bool
    category: str = ""
    reason: str = ""
    flag: str = ""


def detect_meaningless_content(comment: str) -> ContentSignal:
    normalized = normalize_vietnamese_text(comment)
    compact = re.sub(r"\s+", "", normalized)
    tokens = _TOKEN_PATTERN.findall(normalized)

    if not compact:
        return ContentSignal(detected=False)

    if _SYMBOL_ONLY_PATTERN.fullmatch(compact) and len(compact) >= 4:
        return ContentSignal(
            detected=True,
            category="spam",
            reason="Symbol-only meaningless content detected",
            flag="rule_symbol_only_spam",
        )

    if tokens and _is_repeated_meaningless_phrase(tokens):
        return ContentSignal(
            detected=True,
            category="spam",
            reason="Repeated meaningless phrase detected",
            flag="rule_repeated_phrase_spam",
        )

    if len(tokens) == 1:
        token = tokens[0]
        if _is_meaningless_single_token(token):
            return ContentSignal(
                detected=True,
                category="spam",
                reason="Meaningless token pattern detected",
                flag="rule_meaningless_token_spam",
            )

    if _is_multi_token_gibberish(tokens):
        return ContentSignal(
            detected=True,
            category="spam",
            reason="Multi-token gibberish content detected",
            flag="rule_multi_token_gibberish_spam",
        )

    return ContentSignal(detected=False)


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

    category = _pick_emoji_category([item[1] for item in blocked_hits])
    return ContentSignal(
        detected=True,
        category=category,
        reason="Contextually inappropriate emoji-only or emoji-dominant content detected",
        flag="rule_inappropriate_emoji_context",
    )


def _is_repeated_meaningless_phrase(tokens: list[str]) -> bool:
    if len(tokens) < 3:
        return False

    unique_tokens = set(tokens)
    if len(unique_tokens) == 1 and len(next(iter(unique_tokens))) <= 8:
        return True

    most_common_count = max(tokens.count(token) for token in unique_tokens)
    return (
        len(tokens) >= 4
        and len(unique_tokens) <= 2
        and most_common_count / len(tokens) >= 0.75
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
    long_gibberish_tokens = [
        token for token in medium_tokens if _looks_like_gibberish_alpha_token(token)
    ]

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


def _pick_emoji_category(categories: list[str]) -> str:
    if "violent" in categories:
        return "violent"
    if "offensive" in categories:
        return "offensive"
    return "adult"
