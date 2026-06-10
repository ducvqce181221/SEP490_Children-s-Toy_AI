"""
app/application/blog_generation/service.py
-------------------------------------------
Application service for orchestrating the blog content generation workflow.
Includes input validations, caching, intent gates, and safety filters.
"""

from __future__ import annotations

import time
import hashlib
from typing import Any

from app.configs.config import get_settings
from app.core.logging import get_logger
from app.ai.engines.blog_engine import execute_blog_generation, generate_smart_suggestions
from app.ai.engines.content_analyzer import (
    safety_check,
    classify_intent,
    _check_hard_block_emoji,
    _build_source_content_warning,
    output_validation,
    DEFAULT_BLOCK_SUGGESTIONS,
)

logger = get_logger(__name__)

_GENERATE_CACHE_TTL_SECONDS = 300.0
_GENERATE_CACHE_MAX_ITEMS = 128
_GENERATE_RESULT_CACHE: dict[str, tuple[float, tuple[str, str]]] = {}


class BlogContentGenerationError(RuntimeError):
    pass


def _make_generate_cache_key(
    action: str,
    title: str,
    description: str | None,
    prompt_structure: str,
    tone: str,
    category_id: int,
    source_content: str | None,
) -> str:
    raw = "|".join([
        action or "",
        title or "",
        description or "",
        prompt_structure or "",
        tone or "",
        str(category_id),
        source_content or "",
    ])
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _cache_get(key: str) -> tuple[str, str] | None:
    now = time.monotonic()
    cached = _GENERATE_RESULT_CACHE.get(key)
    if not cached:
        return None
    ts, value = cached
    if now - ts > _GENERATE_CACHE_TTL_SECONDS:
        _GENERATE_RESULT_CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: tuple[str, str]) -> None:
    now = time.monotonic()
    if len(_GENERATE_RESULT_CACHE) >= _GENERATE_CACHE_MAX_ITEMS:
        oldest_key = min(_GENERATE_RESULT_CACHE.items(), key=lambda item: item[1][0])[0]
        _GENERATE_RESULT_CACHE.pop(oldest_key, None)
    _GENERATE_RESULT_CACHE[key] = (now, value)


async def generate_blog_content(
    *,
    action: str,
    title: str,
    description: str | None,
    prompt_structure: str,
    tone: str,
    category_id: int,
    source_content: str | None,
) -> tuple[str, str] | dict[str, str | list[str]]:
    logger.info(
        "AI blog generation requested",
        action=action,
        title_len=len(title or ""),
        prompt_len=len(prompt_structure or ""),
        has_source=bool(source_content),
        category_id=category_id,
    )

    # Step 1: Validate request
    if not (title or "").strip() or not (prompt_structure or "").strip() or category_id <= 0:
        return {
            "status": "blocked",
            "violation_type": "unsafe_content",
            "violated_keyword": "validation_error",
            "reason": "invalid_request",
            "suggestions": DEFAULT_BLOCK_SUGGESTIONS[:4],
        }

    # Step 2: Emoji check
    blocked_emoji = _check_hard_block_emoji(title, prompt_structure)
    if blocked_emoji:
        return {
            "status": "blocked",
            "violation_type": "unsafe_content",
            "violated_keyword": blocked_emoji,
            "reason": "inappropriate_emoji",
            "suggestions": DEFAULT_BLOCK_SUGGESTIONS[:4],
        }

    # Step 3: Intent check
    intent = classify_intent(
        title=title,
        description=description,
        prompt_structure=prompt_structure,
        category_id=category_id,
    )
    if str(intent.get("decision")) == "block":
        logger.info(
            "Blog generation blocked by intent gate",
            reason=intent.get("reason"),
            confidence=intent.get("confidence"),
            source=intent.get("source"),
        )
        return {
            "status": "blocked",
            "violation_type": "out_of_scope",
            "violated_keyword": "off_topic",
            "reason": "off_topic",
            "suggestions": [str(intent.get("suggestion", DEFAULT_BLOCK_SUGGESTIONS[0]))] + DEFAULT_BLOCK_SUGGESTIONS[:3],
        }
    if str(intent.get("decision")) == "review":
        logger.info(
            "Intent gate uncertain, allow generation",
            reason=intent.get("reason"),
            confidence=intent.get("confidence"),
            source=intent.get("source"),
        )

    # Step 4: Safety pre-check
    violation = safety_check(title=title, prompt_structure=prompt_structure)
    if violation:
        smart_suggestions = await generate_smart_suggestions(
            title=title,
            content=(description or prompt_structure or "").strip(),
            violated_keyword=str(violation.get("violated_keyword", "")),
            violation_reason=str(violation.get("reason", "")),
        )
        violation["suggestions"] = smart_suggestions[:4] if smart_suggestions else DEFAULT_BLOCK_SUGGESTIONS[:4]
        logger.info(
            "Blog generation blocked by pre-check",
            violation_type=violation.get("violation_type"),
            violated_keyword=violation.get("violated_keyword"),
        )
        return violation

    # System scope check for SourceContent warnings
    source_warning = _build_source_content_warning(source_content)
    if source_warning:
        logger.warning("Source content moderation warning", detail=source_warning)

    # Look up cache
    cache_key = _make_generate_cache_key(
        action=action, title=title, description=description,
        prompt_structure=prompt_structure, tone=tone, category_id=category_id,
        source_content=source_content,
    )
    cached_result = _cache_get(cache_key)
    if cached_result is not None:
        logger.info("AI blog generation cache hit", title_len=len(title or ""))
        return cached_result

    # Invoke the generation engine
    try:
        generated_title, generated_content = await execute_blog_generation(
            action=action, title=title, description=description,
            prompt_structure=prompt_structure, tone=tone, category_id=category_id,
            source_content=source_content,
        )
    except Exception as exc:
        raise BlogContentGenerationError(f"AI content generation failed: {exc}") from exc

    # Validate output safety
    validation_status, validation_payload = output_validation(generated_content)
    if validation_status == "reject":
        return {
            "status": "blocked",
            "violation_type": "unsafe_content",
            "violated_keyword": str(validation_payload),
            "reason": "unsafe_output",
            "suggestions": DEFAULT_BLOCK_SUGGESTIONS[:4],
        }

    result = (generated_title, validation_payload)
    _cache_put(cache_key, result)
    return result
