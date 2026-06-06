from __future__ import annotations

from app.features.moderation.schemas import ModerationDecision

AI_UNAVAILABLE_REASON = "AI moderation is currently unavailable. Your comment will be sent for manual review"

# Must match [dbo].[BlogCommentBanReasons].[Content] values currently in DB.
_CATEGORY_TO_REASON: dict[str, str] = {
    "abusive": "Insulting, abusive, discriminatory, or otherwise inappropriate content",
    "offensive": "Insulting, abusive, discriminatory, or otherwise inappropriate content",
    "profanity_mild": "Insulting, abusive, discriminatory, or otherwise inappropriate content",
    "discriminatory": "Insulting, abusive, discriminatory, or otherwise inappropriate content",
    "harassment": "Insulting, abusive, discriminatory, or otherwise inappropriate content",
    "bullying": "Insulting, abusive, discriminatory, or otherwise inappropriate content",
    "spam": "Spam, ads, links, or repeated meaningless content",
    "ads": "Spam, ads, links, or repeated meaningless content",
    "link_spam": "Spam, ads, links, or repeated meaningless content",
    "competitor_ad": "Spam, ads, links, or repeated meaningless content",
    "unrelated": "Spam, ads, links, or repeated meaningless content",
    "false_info": "Insulting, abusive, discriminatory, or otherwise inappropriate content",
    "misleading": "Insulting, abusive, discriminatory, or otherwise inappropriate content",
    "health_concern": "Insulting, abusive, discriminatory, or otherwise inappropriate content",
    "fake_product": "Insulting, abusive, discriminatory, or otherwise inappropriate content",
    "child_unsafe": "Insulting, abusive, discriminatory, or otherwise inappropriate content",
    "sexual": "Insulting, abusive, discriminatory, or otherwise inappropriate content",
    "adult": "Insulting, abusive, discriminatory, or otherwise inappropriate content",
    "violent": "Insulting, abusive, discriminatory, or otherwise inappropriate content",
    "threat": "Insulting, abusive, discriminatory, or otherwise inappropriate content",
    "privacy": "Sharing private or sensitive personal information",
    "doxxing": "Sharing private or sensitive personal information",
}


def map_ai_category_to_reason_content(
    *,
    decision: ModerationDecision,
    category: str,
) -> str | None:
    if decision != ModerationDecision.REJECTED:
        return None
    return _CATEGORY_TO_REASON.get(category.strip().lower(), "Insulting, abusive, discriminatory, or otherwise inappropriate content")
