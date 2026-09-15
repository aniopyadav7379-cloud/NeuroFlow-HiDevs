import time
from collections.abc import AsyncGenerator
from typing import Any

from anthropic import AsyncAnthropic, RateLimitError

from backend.config import settings

from .base import BaseLLMProvider, ChatMessage, GenerationResult

ANTHROPIC_PRICING = {
    "claude-3-5-sonnet-20240620": {"input": 3.00, "output": 15.00, "context": 200000},
    "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25, "context": 200000},
}


class AnthropicProvider(BaseLLMProvider):
    def __init__(self, model_name: str) -> None:
        super().__init__(model_name)
        api_key = settings.anthropic_api_key or "mock"
        self.client = AsyncAnthropic(api_key=api_key)

        pricing = ANTHROPIC_PRICING.get(model_name, ANTHROPIC_PRICING["claude-3-5-sonnet-20240620"])
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

    def _format_messages(self, messages: list[ChatMessage]) -> tuple[str, list[dict]]:  # type: ignore
        system_text = ""
        api_messages = []
        for msg in messages:
            if msg.role == "system":
                # Anthropic API takes a single top-level `system` parameter
                system_text += str(msg.content) + "\n"
            else:
                if isinstance(msg.content, list):
                    normalized_content = []
                    for block in msg.content:
                        if isinstance(block, dict) and block.get("type") == "image_url":
                            # translate OpenAI image_url to Anthropic image
                            url = block["image_url"]["url"]
                            if url.startswith("data:"):
                                mime_type_b64 = url[5:].split(";base64,")
                                if len(mime_type_b64) == 2:
                                    mime_type, b64_data = mime_type_b64
                                    normalized_content.append(
                                        {
                                            "type": "image",
                                            "source": {
                                                "type": "base64",
                                                "media_type": mime_type,
                                                "data": b64_data,
                                            },
                                        }
                                    )
                                else:
                                    normalized_content.append(block)  # Fallback
                            else:
                                normalized_content.append(
                                    block
                                )  # Cannot handle raw URLs easily in Anthropic without downloading
                        else:
                            normalized_content.append(block)
                    api_messages.append({"role": msg.role, "content": normalized_content})
                else:
                    api_messages.append({"role": msg.role, "content": msg.content})

        return system_text.strip(), api_messages

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

        system_text, api_messages = self._format_messages(messages)

        async def _call() -> Any:  # noqa: ANN401
            return await self.client.messages.create(
                model=self.model_name,
                system=system_text,
                messages=api_messages,  # type: ignore
                max_tokens=kwargs.pop("max_tokens", 4096),
                **kwargs,
            )

        response = await self._execute_with_retry(_call)

        latency_ms = (time.time() - start_time) * 1000

        content = response.content[0].text if response.content else ""
        finish_reason = response.stop_reason or "unknown"

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
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
        system_text, api_messages = self._format_messages(messages)

        # Anthropic streaming is done via context manager, we need a special retry wrapper for it
        # Actually, stream response creation can be rate limited.
        retries = 0
        import asyncio

        while True:
            try:
                async with self.client.messages.stream(
                    model=self.model_name,
                    system=system_text,
                    messages=api_messages,  # type: ignore
                    max_tokens=kwargs.pop("max_tokens", 4096),
                    **kwargs,
                ) as stream:
                    async for text in stream.text_stream:
                        yield text
                break  # Successful stream, break out of retry loop
            except RateLimitError as e:
                if retries >= 3:
                    raise
                retries += 1
                retry_after = (
                    e.response.headers.get("retry-after") if getattr(e, "response", None) else None
                )
                if retry_after:
                    try:
                        await asyncio.sleep(float(retry_after))
                    except ValueError:
                        await asyncio.sleep(2**retries)
                else:
                    await asyncio.sleep(2**retries)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Anthropic does not natively provide a first-party embeddings API endpoint yet.
        raise NotImplementedError(
            "Anthropic provider does not currently support embeddings. Use OpenAI."
        )
