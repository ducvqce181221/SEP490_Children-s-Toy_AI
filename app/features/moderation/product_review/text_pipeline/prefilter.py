r"""
app/features/moderation/product_review/text_pipeline/prefilter.py
------------------------------------------------------------------
Bước 1 của text pipeline: Rule-based pre-filter (không dùng AI, < 1ms).

Reject ngay lập tức nếu:
  - Số ký tự có nghĩa (chữ + số) < 5
  - Spam ký tự lặp: hơn 70% là cùng 1 ký tự và độ dài > 10
  - Chứa URL: https://, www., bit.ly, tinyurl
  - Chứa số điện thoại Việt Nam: 0[0-9]{8,9} hoặc +84...
  - Chứa số tài khoản ngân hàng: \b\d{9,14}\b
"""

from __future__ import annotations

import re
from app.utils.text_utils import has_hard_profanity, clean_and_normalize_text


# ── Precompiled patterns ───────────────────────────────────────────────────────

_URL_PATTERN = re.compile(
    r"https?://"          # http:// or https://
    r"|www\."             # www.
    r"|bit\.ly"
    r"|tinyurl\.com",
    re.IGNORECASE,
)

_VN_PHONE_PATTERN = re.compile(
    r"(?<!\d)"            # not preceded by digit
    r"(0[0-9]{8,9}"       # 0xxxxxxxxx or 0xxxxxxxxxx
    r"|\+84[0-9]{8,9})"   # +84xxxxxxxxx
    r"(?!\d)",            # not followed by digit
)

_BANK_ACCOUNT_PATTERN = re.compile(
    r"\b\d{9,14}\b",
)

_SQL_PATTERN = re.compile(
    r"\b(SELECT\s+[\s\S]*?\s+FROM|INSERT\s+INTO|UPDATE\s+[\s\S]*?\s+SET|DELETE\s+FROM|DROP\s+TABLE|UNION\s+SELECT)\b",
    re.IGNORECASE
)

_EMAIL_PATTERN = re.compile(
    r"\b[a-z0-9._%+-]+(?:\s*(?:dot|\.|\[dot\]|\(dot\))\s*[a-z0-9._%+-]+)*\s*(?:at|@|\[at\]|\(at\))\s*[a-z0-9.-]+\s*(?:dot|\.|\[dot\]|\(dot\))\s*[a-z]{2,}\b",
    re.IGNORECASE
)

_SOCIAL_PATTERN = re.compile(
    r"\b(follow\s+(?:us\s+|me\s+|my\s+)?(?:on\s+)?(?:instagram|ig|facebook|fb|tiktok|zalo|twitter|x)\b|@\w{3,})",
    re.IGNORECASE
)

_SPAM_PATTERN = re.compile(
    r"\b(click\s+now|click\s+here|free\s+rewards|get\s+free|free\s+gift|nhan\s+qua\s+mien\s+phi|nhan\s+thuong|click\s+vao|tang\s+qua)\b",
    re.IGNORECASE
)

_INJECTION_PATTERN = re.compile(
    r"\b(skip\s+all\s+validation|ignore\s+previous\s+rules|bypass\s+rules|internal\s+test\b)",
    re.IGNORECASE
)


class PrefilterResult:
    __slots__ = ("rejected", "reason")

    def __init__(self, rejected: bool, reason: str = "") -> None:
        self.rejected = rejected
        self.reason = reason

    def __repr__(self) -> str:
        return f"PrefilterResult(rejected={self.rejected}, reason={self.reason!r})"


def find_sensitive_patterns(text: str) -> str | None:
    """
    Check if the text contains sensitive patterns like URLs, phone numbers, or bank accounts.
    Returns the failure reason if matched, or None if clean.
    """
    if _URL_PATTERN.search(text):
        return "Chứa URL hoặc link rút gọn"

    if _EMAIL_PATTERN.search(text):
        return "Chứa địa chỉ email (hoặc email viết ẩn danh)"

    if _VN_PHONE_PATTERN.search(text):
        return "Chứa số điện thoại Việt Nam"

    # Exclude phone-like matches already caught above by checking isolated groups
    bank_matches = _BANK_ACCOUNT_PATTERN.findall(text)
    if bank_matches:
        return "Chứa dãy số nghi là số tài khoản ngân hàng"

    if _SQL_PATTERN.search(text):
        return "Chứa cú pháp truy vấn cơ sở dữ liệu (SQL)"

    if _SOCIAL_PATTERN.search(text):
        return "Chứa thông tin liên hệ mạng xã hội / tự quảng cáo"

    if _SPAM_PATTERN.search(text):
        return "Chứa nội dung quảng cáo / spam lôi kéo"

    if _INJECTION_PATTERN.search(text):
        return "Nghi ngờ hành vi bypass bộ lọc kiểm duyệt (Instruction Injection)"

    return None


def run_prefilter(comment: str) -> PrefilterResult:
    """
    Apply all rule-based checks. Returns on first match (fail-fast).

    Args:
        comment: Raw review text.

    Returns:
        PrefilterResult with rejected=True and a reason if any rule fires,
        or rejected=False if all checks pass.
    """
    if not comment or not comment.strip():
        return PrefilterResult(True, "Nội dung rỗng hoặc chỉ có khoảng trắng")

    # 1. Meaningful character count < 5
    meaningful_count = sum(1 for ch in comment if ch.isalnum())
    if meaningful_count < 5:
        return PrefilterResult(
            True,
            f"Quá ít ký tự có nghĩa: {meaningful_count} (tối thiểu 5)",
        )

    # 2. Spam character repetition: > 70% same char AND length > 10
    if len(comment) > 10:
        char_freq = {}
        for ch in comment:
            char_freq[ch] = char_freq.get(ch, 0) + 1
        max_freq = max(char_freq.values())
        if max_freq / len(comment) > 0.70:
            return PrefilterResult(
                True,
                "Spam ký tự lặp: hơn 70% nội dung là cùng một ký tự",
            )

    # Clean and normalize the text using advanced normalization
    normalized = clean_and_normalize_text(comment)

    # 3. Profanity detection
    if has_hard_profanity(comment) or has_hard_profanity(normalized):
        return PrefilterResult(True, "Chứa từ ngữ thô tục cực đoan (chặn tự động)")

    # 4-6. URL, Phone, and Bank Account detection
    sensitive_reason = find_sensitive_patterns(comment)
    if not sensitive_reason:
        sensitive_reason = find_sensitive_patterns(normalized)

    if sensitive_reason:
        return PrefilterResult(True, sensitive_reason)

    return PrefilterResult(False, "")
