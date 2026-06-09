"""
app/ai/engines/moderation_engine.py
-----------------------------------
AI Moderation Engine: builds prompts, calls providers, parses responses,
and applies classification overrides and safety policies.
"""

from __future__ import annotations

import json
from typing import Any

from app.configs.config import get_settings
from app.core.logging import get_logger
from app.schemas.moderation import ModerationDecision, TextPipelineResult
from app.ai.prompts.templates import SYSTEM_PROMPT, build_user_prompt
from app.ai.providers.factory import execute_chat_completion
from app.utils.text_utils import clean_and_normalize_text

logger = get_logger(__name__)

_FALLBACK_RESULT: dict[str, Any] = {
    "decision": "MANUAL_REVIEW",
    "confidence": 0.0,
    "category": "ambiguous",
    "flags": ["llm_parse_error"],
    "reason": "Không thể phân tích kết quả LLM, chuyển kiểm duyệt thủ công",
}


def _parse_llm_json(raw: str) -> dict[str, Any]:
    try:
        raw_clean = raw.strip()
        if raw_clean.startswith("```"):
            lines = raw_clean.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw_clean = "\n".join(lines).strip()

        data = json.loads(raw_clean)
        
        decision_val = data.get("decision", "MANUAL_REVIEW")
        decision_str = str(decision_val).upper()
        if decision_str not in {"APPROVED", "REJECTED", "MANUAL_REVIEW"}:
            decision_str = "MANUAL_REVIEW"
            
        confidence_val = data.get("confidence")
        try:
            confidence = float(confidence_val) if confidence_val is not None else (1.0 if decision_str == "APPROVED" else 0.5)
        except (ValueError, TypeError):
            confidence = 0.5
            
        if not 0.0 <= confidence <= 1.0:
            confidence = 0.5
            
        category = str(data.get("category", "ambiguous")).lower()
        
        flags = data.get("flags")
        if not isinstance(flags, list):
            flags = []
        else:
            flags = [str(f) for f in flags]
            
        reason = str(data.get("reason", ""))
        
        return {
            "decision": decision_str,
            "confidence": confidence,
            "category": category,
            "flags": flags,
            "reason": reason,
        }
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        logger.warning(
            "LLM JSON parsing failed",
            raw_response=raw[:200],
            error=str(exc),
        )
        return {**_FALLBACK_RESULT, "flags": ["llm_parse_error"]}


async def run_llm_classifier(
    comment: str,
    rating: int,
) -> TextPipelineResult:
    """
    Classifies product review text using Groq as primary and DeepSeek as fallback.
    """
    settings = get_settings()
    normalized = clean_and_normalize_text(comment)
    user_message = build_user_prompt(
        content=comment,
        content_type="review",
        rating=rating,
        normalized_content=normalized,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    try:
        raw_completion = await execute_chat_completion(
            primary_provider_name="groq",
            messages=messages,
            temperature=settings.groq_temperature,
            max_tokens=settings.groq_max_tokens,
            response_format={"type": "json_object"},
            fallback_provider_name="deepseek",
        )
        result = _parse_llm_json(raw_completion)
    except Exception as exc:
        logger.error("LLM review classification failed after all retries/fallbacks", error=str(exc))
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


async def run_blog_comment_classifier(
    comment: str,
) -> dict[str, Any]:
    """
    Classifies blog comment text using DeepSeek as primary and Groq as fallback.
    """
    settings = get_settings()
    normalized = clean_and_normalize_text(comment)
    user_message = build_user_prompt(
        content=comment,
        content_type="comment",
        rating=None,
        normalized_content=normalized,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    try:
        raw_completion = await execute_chat_completion(
            primary_provider_name="deepseek",
            messages=messages,
            temperature=settings.blog_deepseek_temperature,
            max_tokens=settings.blog_deepseek_max_tokens,
            response_format={"type": "json_object"},
            fallback_provider_name="groq",
        )
        return _parse_llm_json(raw_completion)
    except Exception as exc:
        logger.error("LLM blog comment classification failed after all retries/fallbacks", error=str(exc))
        return {**_FALLBACK_RESULT, "flags": ["llm_call_failed"]}
