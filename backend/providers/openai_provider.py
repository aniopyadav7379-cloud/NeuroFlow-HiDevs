import time
from collections.abc import AsyncGenerator
from typing import Any

from openai import AsyncOpenAI, RateLimitError

from backend.config import settings

from .base import BaseLLMProvider, ChatMessage, GenerationResult

# Prices in USD per million tokens
OPENAI_PRICING = {
    "gpt-4o": {"input": 2.50, "output": 10.00, "context": 128000},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "context": 128000},
}


class OpenAIProvider(BaseLLMProvider):
    def __init__(self, model_name: str) -> None:
        super().__init__(model_name)
        api_key = settings.openai_api_key or "mock"
        self.client = AsyncOpenAI(api_key=api_key)

        pricing = OPENAI_PRICING.get(model_name, OPENAI_PRICING["gpt-4o-mini"])
        self._cost_input = pricing["input"] / 1_000_000
        self._cost_output = pricing["output"] / 1_000_000
        self._context_window = pricing["context"]

    @property
    def cost_per_input_token(self) -> float:
        return self._cost_input

    @property
    def cost_per_output_token(self) -> float:
        return self._cost_output

    @property
    def context_window(self) -> int:
        return self._context_window  # type: ignore

    def _format_messages(self, messages: list[ChatMessage]) -> list[dict]:  # type: ignore
        return [{"role": msg.role, "content": msg.content} for msg in messages]

    async def _execute_with_retry(self, func: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        import asyncio

        retries = 0
        while True:
            try:
                return await func(*args, **kwargs)
            except RateLimitError as e:
                if retries >= 3:
                    raise
                retries += 1
                retry_after = e.response.headers.get("retry-after") if e.response else None
                if retry_after:
                    try:
                        await asyncio.sleep(float(retry_after))
                    except ValueError:
                        await asyncio.sleep(2**retries)
                else:
                    await asyncio.sleep(2**retries)

    async def complete(self, messages: list[ChatMessage], **kwargs: Any) -> GenerationResult:  # noqa: ANN401
        start_time = time.time()

        async def _call() -> Any:  # noqa: ANN401
            return await self.client.chat.completions.create(
                model=self.model_name,
                messages=self._format_messages(messages),  # type: ignore
                **kwargs,
            )

        response = await self._execute_with_retry(_call)

        latency_ms = (time.time() - start_time) * 1000

        choice = response.choices[0]
        content = choice.message.content or ""
        finish_reason = choice.finish_reason or "unknown"

        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        cost_usd = (input_tokens * self.cost_per_input_token) + (
            output_tokens * self.cost_per_output_token
        )

        return GenerationResult(
            content=content,
            model=self.model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            finish_reason=finish_reason,
        )

    async def stream(self, messages: list[ChatMessage], **kwargs: Any) -> AsyncGenerator[str, None]:  # type: ignore  # noqa: ANN401
        async def _call() -> Any:  # noqa: ANN401
            return await self.client.chat.completions.create(
                model=self.model_name,
                messages=self._format_messages(messages),  # type: ignore
                stream=True,
                **kwargs,
            )

        stream_response = await self._execute_with_retry(_call)
        async for chunk in stream_response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Mock for testing
        if not settings.openai_api_key or settings.openai_api_key == "mock":
            return [[0.1] * 1536 for _ in texts]

        # text-embedding-3-small by default with batch size of 100
        model = "text-embedding-3-small"
        batch_size = 100

        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]

            async def _call() -> Any:  # noqa: ANN401
                return await self.client.embeddings.create(model=model, input=batch)

            response = await self._execute_with_retry(_call)
            batch_embeddings = [data.embedding for data in response.data]
            all_embeddings.extend(batch_embeddings)

        return all_embeddings
