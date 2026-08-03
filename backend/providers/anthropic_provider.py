"""
Anthropic Claude provider implementation.

Same BaseLLMProvider interface as OpenAIProvider, with one structural
difference handled here: the Anthropic API takes `system` as a top-level
request parameter, not as a role inside `messages` — so ChatMessage
objects with role="system" are pulled out and concatenated into `system`
before the call, rather than passed through in the messages list.
"""
import asyncio
import logging
import time
from typing import AsyncGenerator

from anthropic import AsyncAnthropic, RateLimitError

from backend.providers.base import (
    BaseLLMProvider,
    ChatMessage,
    GenerationResult,
    NonRetryableProviderError,
    RetryableProviderError,
)

logger = logging.getLogger("neuroflow.providers.anthropic")

# USD per million tokens.
PRICE_TABLE_PER_MILLION = {
    "claude-opus-4-8": {"input": 15.00, "output": 75.00},
    "claude-sonnet-5": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
}

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_RETRIES = 3
MAX_TOKENS_DEFAULT = 4096

# Anthropic has no first-party embeddings endpoint; NeuroFlow's default
# embedding path goes through the OpenAI provider (see router.py /
# client.py). embed() is still implemented to satisfy the interface and
# to support a future voyageai-backed path without changing callers.
EMBEDDINGS_NOT_SUPPORTED_MSG = (
    "AnthropicProvider has no native embeddings endpoint — "
    "route embedding tasks to a provider that supports them."
)


def _price_per_token(model: str, kind: str) -> float:
    table = PRICE_TABLE_PER_MILLION.get(model)
    if table is None:
        raise NonRetryableProviderError(f"no price table entry for model '{model}'")
    return table[kind] / 1_000_000


def _split_system_and_messages(messages: list[ChatMessage]) -> tuple[str | None, list[dict]]:
    system_parts: list[str] = []
    converted: list[dict] = []
    for m in messages:
        if m.role == "system":
            # system content is always text for NeuroFlow's use case
            system_parts.append(m.content if isinstance(m.content, str) else str(m.content))
        else:
            converted.append({"role": m.role, "content": m.content})
    system = "\n\n".join(system_parts) if system_parts else None
    return system, converted


class AnthropicProvider(BaseLLMProvider):
    provider_name = "anthropic"

    def __init__(self, api_key: str, default_model: str = DEFAULT_MODEL):
        self._client = AsyncAnthropic(api_key=api_key)
        self.default_model = default_model

    async def _with_retries(self, coro_fn, *args, **kwargs):
        attempt = 0
        while True:
            try:
                return await coro_fn(*args, **kwargs)
            except RateLimitError as e:
                attempt += 1
                if attempt > MAX_RETRIES:
                    raise RetryableProviderError(f"rate limited after {MAX_RETRIES} retries") from e
                retry_after = getattr(e, "retry_after", None) or 2 ** (attempt - 1)
                logger.warning(
                    "anthropic rate limited (attempt %d/%d), waiting %.1fs",
                    attempt, MAX_RETRIES, retry_after,
                )
                await asyncio.sleep(retry_after)

    async def complete(self, messages: list[ChatMessage], **kwargs) -> GenerationResult:
        model = kwargs.pop("model", self.default_model)
        max_tokens = kwargs.pop("max_tokens", MAX_TOKENS_DEFAULT)
        system, converted = _split_system_and_messages(messages)
        started = time.perf_counter()

        response = await self._with_retries(
            self._client.messages.create,
            model=model,
            system=system,
            messages=converted,
            max_tokens=max_tokens,
            **kwargs,
        )
        latency_ms = (time.perf_counter() - started) * 1000

        content = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        cost = (
            response.usage.input_tokens * _price_per_token(model, "input")
            + response.usage.output_tokens * _price_per_token(model, "output")
        )

        return GenerationResult(
            content=content,
            model=model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost,
            finish_reason=response.stop_reason or "unknown",
        )

    async def stream(self, messages: list[ChatMessage], **kwargs) -> AsyncGenerator[str, None]:
        model = kwargs.pop("model", self.default_model)
        max_tokens = kwargs.pop("max_tokens", MAX_TOKENS_DEFAULT)
        system, converted = _split_system_and_messages(messages)

        attempt = 0
        while True:
            try:
                async with self._client.messages.stream(
                    model=model,
                    system=system,
                    messages=converted,
                    max_tokens=max_tokens,
                    **kwargs,
                ) as stream:
                    async for text in stream.text_stream:
                        yield text
                return
            except RateLimitError as e:
                attempt += 1
                if attempt > MAX_RETRIES:
                    raise RetryableProviderError(f"rate limited after {MAX_RETRIES} retries") from e
                retry_after = getattr(e, "retry_after", None) or 2 ** (attempt - 1)
                logger.warning(
                    "anthropic stream rate limited (attempt %d/%d), waiting %.1fs",
                    attempt, MAX_RETRIES, retry_after,
                )
                await asyncio.sleep(retry_after)

    async def embed(self, texts: list[str], **kwargs) -> list[list[float]]:
        raise NonRetryableProviderError(EMBEDDINGS_NOT_SUPPORTED_MSG)

    @property
    def cost_per_input_token(self) -> float:
        return _price_per_token(self.default_model, "input")

    @property
    def cost_per_output_token(self) -> float:
        return _price_per_token(self.default_model, "output")

    @property
    def context_window(self) -> int:
        return 200_000
