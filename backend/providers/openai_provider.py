"""
OpenAI (or any OpenAI-compatible endpoint) provider implementation.
"""
import asyncio
import logging
import time
from typing import AsyncGenerator

from openai import AsyncOpenAI
from openai import RateLimitError

from backend.providers.base import (
    BaseLLMProvider,
    ChatMessage,
    GenerationResult,
    NonRetryableProviderError,
    RetryableProviderError,
)

logger = logging.getLogger("neuroflow.providers.openai")

# USD per million tokens -> stored per-token internally for cost math.
PRICE_TABLE_PER_MILLION = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
}

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_BATCH_SIZE = 100
MAX_RETRIES = 3


def _price_per_token(model: str, kind: str) -> float:
    table = PRICE_TABLE_PER_MILLION.get(model)
    if table is None:
        # Unknown model — don't silently report zero cost, which would
        # corrupt cost-based routing decisions and Redis cost metrics.
        raise NonRetryableProviderError(f"no price table entry for model '{model}'")
    return table[kind] / 1_000_000


def _to_openai_messages(messages: list[ChatMessage]) -> list[dict]:
    return [{"role": m.role, "content": m.content} for m in messages]


class OpenAIProvider(BaseLLMProvider):
    provider_name = "openai"

    def __init__(self, api_key: str, base_url: str | None = None, default_model: str = DEFAULT_MODEL):
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.default_model = default_model

    async def _with_retries(self, coro_fn, *args, **kwargs):
        """Calls coro_fn(*args, **kwargs) with exponential backoff on
        RateLimitError, up to MAX_RETRIES attempts, honoring the API's
        retry_after hint when present."""
        attempt = 0
        while True:
            try:
                return await coro_fn(*args, **kwargs)
            except RateLimitError as e:
                attempt += 1
                if attempt > MAX_RETRIES:
                    raise RetryableProviderError(f"rate limited after {MAX_RETRIES} retries") from e
                retry_after = getattr(e, "retry_after", None)
                if retry_after is None:
                    # exponential backoff fallback: 1s, 2s, 4s
                    retry_after = 2 ** (attempt - 1)
                logger.warning(
                    "openai rate limited (attempt %d/%d), waiting %.1fs",
                    attempt, MAX_RETRIES, retry_after,
                )
                await asyncio.sleep(retry_after)

    async def complete(self, messages: list[ChatMessage], **kwargs) -> GenerationResult:
        model = kwargs.pop("model", self.default_model)
        started = time.perf_counter()

        response = await self._with_retries(
            self._client.chat.completions.create,
            model=model,
            messages=_to_openai_messages(messages),
            **kwargs,
        )
        latency_ms = (time.perf_counter() - started) * 1000

        choice = response.choices[0]
        usage = response.usage
        cost = (
            usage.prompt_tokens * _price_per_token(model, "input")
            + usage.completion_tokens * _price_per_token(model, "output")
        )

        return GenerationResult(
            content=choice.message.content or "",
            model=model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            latency_ms=latency_ms,
            cost_usd=cost,
            finish_reason=choice.finish_reason or "unknown",
        )

    async def stream(self, messages: list[ChatMessage], **kwargs) -> AsyncGenerator[str, None]:
        model = kwargs.pop("model", self.default_model)

        attempt = 0
        while True:
            try:
                stream = await self._client.chat.completions.create(
                    model=model,
                    messages=_to_openai_messages(messages),
                    stream=True,
                    **kwargs,
                )
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        yield delta
                return
            except RateLimitError as e:
                attempt += 1
                if attempt > MAX_RETRIES:
                    raise RetryableProviderError(f"rate limited after {MAX_RETRIES} retries") from e
                retry_after = getattr(e, "retry_after", None) or 2 ** (attempt - 1)
                logger.warning(
                    "openai stream rate limited (attempt %d/%d), waiting %.1fs",
                    attempt, MAX_RETRIES, retry_after,
                )
                await asyncio.sleep(retry_after)

    async def embed(self, texts: list[str], **kwargs) -> list[list[float]]:
        model = kwargs.pop("model", DEFAULT_EMBEDDING_MODEL)
        vectors: list[list[float]] = []

        for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[i : i + EMBEDDING_BATCH_SIZE]
            response = await self._with_retries(
                self._client.embeddings.create,
                model=model,
                input=batch,
            )
            vectors.extend(item.embedding for item in response.data)

        return vectors

    @property
    def cost_per_input_token(self) -> float:
        return _price_per_token(self.default_model, "input")

    @property
    def cost_per_output_token(self) -> float:
        return _price_per_token(self.default_model, "output")

    @property
    def context_window(self) -> int:
        # gpt-4o / gpt-4o-mini both have a 128k context window.
        return 128_000
