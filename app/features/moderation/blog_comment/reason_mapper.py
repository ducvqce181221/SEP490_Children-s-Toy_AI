from __future__ import annotations

from app.features.moderation.schemas import ModerationDecision

AI_UNAVAILABLE_REASON = "AI moderation is currently unavailable. Your comment will be sent for manual review"

_CATEGORY_TO_REASON: dict[str, str] = {
    "abusive": "Insulting, abusive, or discriminatory content",
    "offensive": "Insulting, abusive, or discriminatory content",
    "discriminatory": "Insulting, abusive, or discriminatory content",
    "spam": "Spam, ads, links, or repeated meaningless content",
    "ads": "Spam, ads, links, or repeated meaningless content",
    "link_spam": "Spam, ads, links, or repeated meaningless content",
    "unrelated": "Content unrelated to the blog or product",
    "false_info": "False or misleading information",
    "misleading": "False or misleading information",
    "child_unsafe": "Content unsuitable for children",
    "sexual": "Content unsuitable for children",
    "adult": "Content unsuitable for children",
    "privacy": "Sharing private or sensitive personal information",
    "doxxing": "Sharing private or sensitive personal information",
    "harassment": "Harassment, bullying, or targeting specific users",
    "bullying": "Harassment, bullying, or targeting specific users",
    "violent": "Violent content, threats, or incitement",
    "threat": "Violent content, threats, or incitement",
}


def map_ai_category_to_reason_content(
    *,
    decision: ModerationDecision,
    category: str,
) -> str | None:
    if decision != ModerationDecision.REJECTED:
        return None
    return _CATEGORY_TO_REASON.get(category.strip().lower(), "Content unsuitable for children")


