"""
app/features/moderation/text_pipeline/llm_classifier.py
---------------------------------------------------------
Bước 2 của text pipeline: Groq LLM Classifier.

Gọi Groq LLM và trả về kết quả phân loại có cấu trúc.
Nếu parse JSON thất bại → mặc định MANUAL_REVIEW (an toàn).
"""

from __future__ import annotations

from app.features.moderation.schemas import ModerationDecision, TextPipelineResult
from app.llm.client import get_groq_client
from app.core.logging import get_logger

logger = get_logger(__name__)


async def run_llm_classifier(
    comment: str,
    rating: int,
) -> TextPipelineResult:
    """
    Step 2: Call Groq LLM to classify the review text.

    Args:
        comment: Review text content.
        rating: Star rating 1-5.

    Returns:
        TextPipelineResult with LLM decision, confidence, category, flags, reason.
    """
    try:
        client = get_groq_client()
        result = await client.classify_text(comment=comment, rating=rating)
    except Exception as exc:
        logger.error("LLM classification failed after retries", error=str(exc))
        return TextPipelineResult(
            decision=ModerationDecision.MANUAL_REVIEW,
            confidence=0.0,
            category="ambiguous",
            flags=["llm_call_failed"],
            reason="Lỗi khi gọi LLM, chuyển kiểm duyệt thủ công",
            decided_by="llm_error",
        )

    decision_str = result.get("decision", "MANUAL_REVIEW").upper()
    try:
        decision = ModerationDecision(decision_str)
    except ValueError:
        decision = ModerationDecision.MANUAL_REVIEW

    return TextPipelineResult(
        decision=decision,
        confidence=float(result.get("confidence", 0.0)),
        category=str(result.get("category", "ambiguous")),
        flags=list(result.get("flags", [])),
        reason=str(result.get("reason", "")),
        decided_by="llm",
        raw_llm_result=result,
    )
