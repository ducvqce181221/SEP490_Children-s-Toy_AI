from __future__ import annotations

import re
from dataclasses import dataclass

from app.features.moderation.blog_comment.social_contact_detector import (
    detect_social_contact_info,
)
from app.utils.text_utils import has_hard_profanity

_URL_PATTERN = re.compile(
    r"https?://"
    r"|www\."
    r"|bit\.ly"
    r"|tinyurl\.com",
    re.IGNORECASE,
)

_EMAIL_PATTERN = re.compile(
    r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b",
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

@dataclass(frozen=True)
class BlogCommentPrefilterResult:
    rejected: bool
    category: str = ""
    reason: str = ""
    flag: str = ""


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


def run_blog_comment_prefilter(comment: str) -> BlogCommentPrefilterResult:
    if not comment or not comment.strip():
        return BlogCommentPrefilterResult(
            rejected=True,
            category="spam",
            reason="Empty or whitespace-only content",
            flag="rule_empty_content",
        )

    if len(comment) > 10:
        char_freq: dict[str, int] = {}
        for ch in comment:
            char_freq[ch] = char_freq.get(ch, 0) + 1
        max_freq = max(char_freq.values())
        if max_freq / len(comment) > 0.70:
            return BlogCommentPrefilterResult(
                rejected=True,
                category="spam",
                reason="Repeated-character spam pattern detected",
                flag="rule_repeated_char_spam",
            )

    if _URL_PATTERN.search(comment):
        return BlogCommentPrefilterResult(
            rejected=True,
            category="spam",
            reason="Contains URL or shortened link",
            flag="rule_url_detected",
        )

    social_contact = detect_social_contact_info(comment)
    if social_contact.detected:
        return BlogCommentPrefilterResult(
            rejected=True,
            category="spam",
            reason=social_contact.reason,
            flag=social_contact.flag,
        )

    if _EMAIL_PATTERN.search(comment):
        return BlogCommentPrefilterResult(
            rejected=True,
            category="privacy",
            reason="Contains an email address",
            flag="rule_email_detected",
        )

    if _contains_vn_phone(comment):
        return BlogCommentPrefilterResult(
            rejected=True,
            category="privacy",
            reason="Contains a Vietnamese phone number",
            flag="rule_phone_detected",
        )

    if _contains_bank_account_like_number(comment):
        return BlogCommentPrefilterResult(
            rejected=True,
            category="privacy",
            reason="Contains bank-account-like number sequence",
            flag="rule_bank_account_detected",
        )

    if _contains_address_like_personal_info(comment):
        return BlogCommentPrefilterResult(
            rejected=True,
            category="privacy",
            reason="Contains detailed personal address information",
            flag="rule_address_detected",
        )

    if has_hard_profanity(comment):
        return BlogCommentPrefilterResult(
            rejected=True,
            category="offensive",
            reason="Contains severe profanity",
            flag="rule_hard_profanity_reject",
        )

    return BlogCommentPrefilterResult(rejected=False)
