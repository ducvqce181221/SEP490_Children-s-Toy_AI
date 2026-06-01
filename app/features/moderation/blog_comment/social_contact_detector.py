from __future__ import annotations

import re
from dataclasses import dataclass

from app.utils.text_utils import normalize_vietnamese_text

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
    "instagram",
    "tiktok",
    "discord",
    "twitter",
    "facebook",
    "messenger",
    "telegram",
    "whatsapp",
    "trend",
    "video",
    "shop",
}


@dataclass(frozen=True)
class SocialContactDetectionResult:
    detected: bool
    reason: str = ""
    flag: str = ""


def detect_social_contact_info(comment: str) -> SocialContactDetectionResult:
    if not comment or not comment.strip():
        return SocialContactDetectionResult(detected=False)

    normalized = normalize_vietnamese_text(comment)
    if not normalized:
        return SocialContactDetectionResult(detected=False)

    if _SOCIAL_HANDLE_PATTERN.search(comment):
        return SocialContactDetectionResult(
            detected=True,
            reason="Contains social media handle or username",
            flag="rule_social_handle_detected",
        )

    if _DISCORD_TAG_PATTERN.search(comment) and "discord" in normalized:
        return SocialContactDetectionResult(
            detected=True,
            reason="Contains Discord tag for external contact",
            flag="rule_discord_tag_detected",
        )

    platform_mentioned = _SOCIAL_PLATFORM_PATTERN.search(normalized) is not None
    contact_intent = _CONTACT_INTENT_PATTERN.search(normalized) is not None
    has_social_channel_phrase = (
        "mang xa hoi" in normalized
        or "ket noi ben ngoai" in normalized
        or "social media" in normalized
        or "outside the platform" in normalized
        or "off platform" in normalized
    )
    if (
        (platform_mentioned and contact_intent)
        or (has_social_channel_phrase and contact_intent)
    ):
        return SocialContactDetectionResult(
            detected=True,
            reason="Encourages contact via social media",
            flag="rule_social_contact_intent_detected",
        )

    for match in _PLATFORM_WITH_USERNAME_PATTERN.finditer(normalized):
        username = match.group(1)
        if _looks_like_username(username):
            return SocialContactDetectionResult(
                detected=True,
                reason="Contains social username on platform",
                flag="rule_social_username_detected",
            )

    for match in _USERNAME_ON_PLATFORM_PATTERN.finditer(normalized):
        username = match.group(1)
        if _looks_like_username(username):
            return SocialContactDetectionResult(
                detected=True,
                reason="Contains likely social account mention",
                flag="rule_social_username_detected",
            )

    return SocialContactDetectionResult(detected=False)


def _looks_like_username(token: str) -> bool:
    lowered = token.strip().lower()
    if (
        not lowered
        or lowered.isdigit()
        or lowered in _NON_USERNAME_TOKENS
    ):
        return False

    return (
        "_" in lowered
        or "." in lowered
        or any(ch.isdigit() for ch in lowered)
        or len(lowered) >= 9
    )
