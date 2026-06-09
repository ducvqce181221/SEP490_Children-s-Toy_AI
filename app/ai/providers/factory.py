"""
app/ai/providers/factory.py
---------------------------
Factory and routing layer for AI providers.
Resolves providers and coordinates API execution with fallback fallback.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.ai.providers.base import AIProvider, AIProviderError
from app.ai.providers.groq import GroqProvider
from app.ai.providers.deepseek import DeepSeekProvider

logger = get_logger(__name__)

# Registry of initialized provider instances
_providers: dict[str, AIProvider] = {}


def get_provider(name: str) -> AIProvider:
    """
    Get or initialize a model provider by name.
    Supported names: 'groq', 'deepseek'.
    """
    name = name.lower().strip()
    if name not in _providers:
        if name == "groq":
            _providers[name] = GroqProvider()
        elif name == "deepseek":
            _providers[name] = DeepSeekProvider()
        else:
            raise ValueError(f"Unsupported provider: {name}")
    return _providers[name]


async def execute_chat_completion(
    primary_provider_name: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    response_format: dict[str, Any] | None = None,
    fallback_provider_name: str | None = None,
    **kwargs: Any,
) -> str:
    """
    Execute chat completion with transparent fallback to another provider.

    Args:
        primary_provider_name: Name of the primary provider (e.g. 'groq' or 'deepseek').
        messages: Prompt messages array.
        temperature: Temperature value.
        max_tokens: Max completion tokens.
        response_format: Output format specifications.
        fallback_provider_name: Optional name of the fallback provider to try on failure.

    Returns:
        The generated text completion.

    Raises:
        AIProviderError: If both primary and fallback calls fail.
    """
    try:
        provider = get_provider(primary_provider_name)
        logger.info("Calling primary AI provider", provider=primary_provider_name)
        return await provider.chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            **kwargs,
        )
    except Exception as exc:
        logger.warning(
            "Primary AI provider failed",
            provider=primary_provider_name,
            error=str(exc),
        )
        if not fallback_provider_name:
            if isinstance(exc, AIProviderError):
                raise
            raise AIProviderError(f"Primary provider {primary_provider_name} failed: {exc}") from exc

        try:
            logger.info("Executing fallback AI provider", provider=fallback_provider_name)
            fallback_provider = get_provider(fallback_provider_name)
            return await fallback_provider.chat_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                **kwargs,
            )
        except Exception as fallback_exc:
            logger.error(
                "Fallback AI provider also failed",
                fallback_provider=fallback_provider_name,
                error=str(fallback_exc),
            )
            if isinstance(fallback_exc, AIProviderError):
                raise
            raise AIProviderError(
                f"Both primary ({primary_provider_name}) and fallback ({fallback_provider_name}) providers failed."
            ) from fallback_exc
