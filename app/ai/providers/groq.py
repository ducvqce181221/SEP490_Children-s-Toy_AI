"""
app/ai/providers/groq.py
-------------------------
Groq model provider implementation.
"""

from __future__ import annotations

from typing import Any
from groq import AsyncGroq, APIConnectionError, APIStatusError, APITimeoutError

from app.configs.config import get_settings
from app.core.logging import get_logger
from app.ai.providers.base import AIProvider, AIProviderError
from app.utils.retry import async_retry

logger = get_logger(__name__)


class GroqProvider(AIProvider):

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.groq_api_key:
            raise ValueError("Missing API key for Groq")
        
        client_kwargs: dict[str, Any] = {"api_key": settings.groq_api_key}
        if settings.groq_base_url:
            client_kwargs["base_url"] = settings.groq_base_url
            
        self._client = AsyncGroq(**client_kwargs)
        self._model = settings.groq_model

    @async_retry(
        max_attempts=3,
        min_wait=1.0,
        max_wait=8.0,
        exceptions=(APIConnectionError, APITimeoutError),
    )
    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            call_kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if response_format:
                call_kwargs["response_format"] = response_format

            response = await self._client.chat.completions.create(**call_kwargs)
            return response.choices[0].message.content or ""
        except APIStatusError as exc:
            logger.error(
                "Groq API returned error status",
                status=exc.status_code,
                message=exc.message,
            )
            raise AIProviderError(f"Groq API error {exc.status_code}: {exc.message}") from exc
        except Exception as exc:
            logger.error("Groq chat completion call failed", error=str(exc))
            raise AIProviderError(f"Groq failure: {exc}") from exc
