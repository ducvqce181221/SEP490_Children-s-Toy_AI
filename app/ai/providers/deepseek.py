"""
app/ai/providers/deepseek.py
----------------------------
DeepSeek model provider implementation using httpx.
"""

from __future__ import annotations

import json
from typing import Any
import httpx

from app.configs.config import get_settings
from app.core.logging import get_logger
from app.ai.providers.base import AIProvider, AIProviderError
from app.utils.retry import async_retry

logger = get_logger(__name__)


class DeepSeekProvider(AIProvider):

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.blog_deepseek_api_key:
            raise ValueError("Missing API key for DeepSeek")
            
        self._api_key = settings.blog_deepseek_api_key
        self._model = settings.blog_deepseek_model
        self._endpoints = self._build_endpoints(settings.blog_deepseek_base_url)
        self._timeout = settings.blog_deepseek_timeout_seconds
        self._retry_attempts = settings.blog_deepseek_retry_attempts

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
    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        last_error = ""
        for endpoint in self._endpoints:
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(endpoint, headers=headers, json=payload)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.warning("DeepSeek timeout/connection error on endpoint", endpoint=endpoint, error=str(exc))
                raise
            except httpx.HTTPError as exc:
                last_error = str(exc)
                logger.error("DeepSeek API request failed", endpoint=endpoint, error=str(exc))
                continue

            if response.status_code == 404:
                last_error = "404 Not Found"
                logger.warning("DeepSeek endpoint returned 404", endpoint=endpoint)
                continue

            if response.status_code >= 400:
                last_error = f"HTTP {response.status_code}"
                logger.error("DeepSeek API returned error status", endpoint=endpoint, status=response.status_code)
                continue

            try:
                body = response.json()
                return body["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                logger.error("DeepSeek response parse envelope failed", endpoint=endpoint, error=str(exc))
                raise AIProviderError("DeepSeek payload parsing failure") from exc

        raise AIProviderError(f"All DeepSeek endpoints failed. Last error: {last_error}")
