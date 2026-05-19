"""
app/llm/client.py
-----------------
Async Groq LLM client for review text classification.
"""

from __future__ import annotations

import json
from typing import Any

from groq import AsyncGroq
from groq import APIConnectionError, APIStatusError, APITimeoutError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from app.utils.retry import async_retry

logger = get_logger(__name__)

_FALLBACK_RESULT: dict[str, Any] = {
    "decision": "MANUAL_REVIEW",
    "confidence": 0.0,
    "category": "ambiguous",
    "flags": ["llm_parse_error"],
    "reason": "Không thể phân tích kết quả LLM, chuyển kiểm duyệt thủ công",
}


class GroqClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncGroq(api_key=settings.groq_api_key)
        self._model = settings.groq_model
        self._temperature = settings.groq_temperature
        self._max_tokens = settings.groq_max_tokens

    @async_retry(
        max_attempts=3, min_wait=1.0, max_wait=8.0,
        exceptions=(APIConnectionError, APITimeoutError),
    )
    async def classify_text(self, comment: str, rating: int) -> dict[str, Any]:
        user_message = build_user_prompt(comment=comment, rating=rating)
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                response_format={"type": "json_object"},
            )
        except APIStatusError as exc:
            logger.error("Groq API returned error status", status=exc.status_code, message=exc.message)
            return {**_FALLBACK_RESULT, "flags": [f"groq_api_error_{exc.status_code}"]}

        raw_content = response.choices[0].message.content or ""
        return self._parse_response(raw_content)

    def _parse_response(self, raw: str) -> dict[str, Any]:
        try:
            data = json.loads(raw)
            required = {"decision", "confidence", "category", "flags", "reason"}
            if not required.issubset(data.keys()):
                raise ValueError(f"Missing keys: {required - data.keys()}")
            data["decision"] = str(data["decision"]).upper()
            if data["decision"] not in {"APPROVED", "REJECTED", "MANUAL_REVIEW"}:
                raise ValueError(f"Invalid decision: {data['decision']}")
            data["confidence"] = float(data["confidence"])
            if not 0.0 <= data["confidence"] <= 1.0:
                data["confidence"] = 0.0
            if not isinstance(data["flags"], list):
                data["flags"] = []
            return data
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.warning("LLM response parse failed", raw_response=raw[:200], error=str(exc))
            return {**_FALLBACK_RESULT, "flags": ["llm_parse_error"]}


_groq_client: GroqClient | None = None


def get_groq_client() -> GroqClient:
    global _groq_client
    if _groq_client is None:
        _groq_client = GroqClient()
    return _groq_client
