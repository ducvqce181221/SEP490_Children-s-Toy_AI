"""
app/llm/client.py
-----------------
Async LLM clients for text moderation classification.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from groq import APIConnectionError, APIStatusError, APITimeoutError
from groq import AsyncGroq

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
    "reason": "Khong the phan tich ket qua LLM, chuyen kiem duyet thu cong",
}


class _BaseModerationClient:
    def __init__(
        self,
        *,
        provider_name: str,
        api_key: str,
        model: str,
        base_url: str | None,
        temperature: float,
        max_tokens: int,
    ) -> None:
        if not api_key:
            raise ValueError(f"Missing API key for {provider_name}")
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self._provider_name = provider_name
        self._client = AsyncGroq(**client_kwargs)
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    @async_retry(
        max_attempts=3,
        min_wait=1.0,
        max_wait=8.0,
        exceptions=(APIConnectionError, APITimeoutError),
    )
    async def classify_text(
        self,
        comment: str,
        content_type: str = "review",
        rating: int | None = None,
    ) -> dict[str, Any]:
        user_message = build_user_prompt(content=comment, content_type=content_type, rating=rating)
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
            logger.error(
                "LLM API returned error status",
                provider=self._provider_name,
                status=exc.status_code,
                message=exc.message,
            )
            return {**_FALLBACK_RESULT, "flags": [f"llm_api_error_{exc.status_code}"]}

        raw_content = response.choices[0].message.content or ""
        return self._parse_response(raw_content)

    def _parse_response(self, raw: str) -> dict[str, Any]:
        try:
            # Clean markdown code block fences if present
            raw_clean = raw.strip()
            if raw_clean.startswith("```"):
                # strip block fences
                lines = raw_clean.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                raw_clean = "\n".join(lines).strip()

            data = json.loads(raw_clean)
            
            # Robust, forgiving extraction
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
                "LLM response parse failed",
                provider=self._provider_name,
                raw_response=raw[:200],
                error=str(exc),
            )
            return {**_FALLBACK_RESULT, "flags": ["llm_parse_error"]}



class GroqClient(_BaseModerationClient):
    def __init__(self) -> None:
        settings = get_settings()
        super().__init__(
            provider_name="groq",
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            base_url=settings.groq_base_url,
            temperature=settings.groq_temperature,
            max_tokens=settings.groq_max_tokens,
        )


class BlogDeepSeekClient(_BaseModerationClient):
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.blog_deepseek_api_key:
            raise ValueError("Missing API key for deepseek_blog")
        self._provider_name = "deepseek_blog"
        self._api_key = settings.blog_deepseek_api_key
        self._model = settings.blog_deepseek_model
        self._temperature = settings.blog_deepseek_temperature
        self._max_tokens = settings.blog_deepseek_max_tokens
        self._endpoints = self._build_endpoints(settings.blog_deepseek_base_url)

    @staticmethod
    def _build_endpoints(base_url: str) -> list[str]:
        base = (base_url or "https://api.deepseek.com").rstrip("/")
        if base.endswith("/chat/completions"):
            return [base]
        if base.endswith("/v1"):
            return [f"{base}/chat/completions"]
        return [f"{base}/chat/completions", f"{base}/v1/chat/completions"]

    @async_retry(
        max_attempts=3,
        min_wait=1.0,
        max_wait=8.0,
        exceptions=(httpx.ConnectError, httpx.TimeoutException),
    )
    async def classify_text(
        self,
        comment: str,
        content_type: str = "review",
        rating: int | None = None,
    ) -> dict[str, Any]:
        user_message = build_user_prompt(content=comment, content_type=content_type, rating=rating)
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        for endpoint in self._endpoints:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(endpoint, headers=headers, json=payload)
            except (httpx.ConnectError, httpx.TimeoutException):
                raise
            except httpx.HTTPError as exc:
                logger.error(
                    "LLM API request failed",
                    provider=self._provider_name,
                    endpoint=endpoint,
                    error=str(exc),
                )
                return {**_FALLBACK_RESULT, "flags": ["llm_api_request_error"]}

            if response.status_code == 404:
                logger.warning(
                    "DeepSeek endpoint returned 404, trying next endpoint",
                    provider=self._provider_name,
                    endpoint=endpoint,
                )
                continue

            if response.status_code >= 400:
                logger.error(
                    "LLM API returned error status",
                    provider=self._provider_name,
                    endpoint=endpoint,
                    status=response.status_code,
                    message=response.text[:200],
                )
                return {**_FALLBACK_RESULT, "flags": [f"llm_api_error_{response.status_code}"]}

            try:
                body = response.json()
                raw_content = body["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                logger.warning(
                    "LLM response parse envelope failed",
                    provider=self._provider_name,
                    endpoint=endpoint,
                    error=str(exc),
                )
                return {**_FALLBACK_RESULT, "flags": ["llm_parse_error"]}
            return self._parse_response(raw_content)

        logger.error(
            "LLM API returned 404 for all DeepSeek endpoints",
            provider=self._provider_name,
            endpoints=self._endpoints,
        )
        return {**_FALLBACK_RESULT, "flags": ["llm_api_error_404"]}


_groq_client: GroqClient | None = None
_blog_deepseek_client: BlogDeepSeekClient | None = None


def get_groq_client() -> GroqClient:
    global _groq_client
    if _groq_client is None:
        _groq_client = GroqClient()
    return _groq_client


def get_blog_deepseek_client() -> BlogDeepSeekClient:
    global _blog_deepseek_client
    if _blog_deepseek_client is None:
        _blog_deepseek_client = BlogDeepSeekClient()
    return _blog_deepseek_client
