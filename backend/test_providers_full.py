import asyncio
import os
import sys
import time
from typing import Any

sys.path.append(".")

# Mock environment variables before importing settings
os.environ["OPENAI_API_KEY"] = "mock_key"
os.environ["ANTHROPIC_API_KEY"] = "mock_key"

from unittest.mock import AsyncMock

from httpx import Request, Response
from openai import RateLimitError as OpenAIRateLimitError

# Opentelemetry testing
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from backend.providers.anthropic_provider import AnthropicProvider
from backend.providers.base import BaseLLMProvider, ChatMessage, GenerationResult
from backend.providers.client import NeuroFlowClient
from backend.providers.openai_provider import OpenAIProvider
from backend.providers.router import ModelRouter, RoutingCriteria


async def test_full_interface() -> None:
    print("Testing BaseLLMProvider interface implementation...")
    openai = OpenAIProvider("gpt-4o-mini")
    anthropic = AnthropicProvider("claude-3-haiku-20240307")
    assert isinstance(openai, BaseLLMProvider)
    assert isinstance(anthropic, BaseLLMProvider)
    print("Ã¢Å“â€¦ Providers implement full interface.")


async def test_streaming_mock() -> None:
    print("Testing progressive streaming...")
    provider = OpenAIProvider("gpt-4o-mini")

    async def mock_create(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        async def mock_stream() -> Any:  # noqa: ANN401
            class MockChoice:
                def __init__(self, content: Any) -> None:  # noqa: ANN401
                    class Delta:
                        pass

                    self.delta = Delta()
                    self.delta.content = content  # type: ignore

            class MockChunk:
                def __init__(self, content: Any) -> None:  # noqa: ANN401
                    self.choices = [MockChoice(content)]

            yield MockChunk("Hello")
            yield MockChunk(" World")
            yield MockChunk("!")

        # Simulate an AsyncStream object that allows async iteration
        class MockAsyncStream:
            def __aiter__(self) -> Any:  # noqa: ANN401
                return mock_stream()

        return MockAsyncStream()

    provider.client.chat.completions.create = AsyncMock(side_effect=mock_create)  # type: ignore

    print("Stream Output: ", end="")
    messages = [ChatMessage(role="user", content="say hello")]
    async for token in provider.stream(messages):
        print(token, end="", flush=True)
    print("\nÃ¢Å“â€¦ Stream yielded progressively.")


async def test_rate_limit_retry() -> None:
    print("Testing Rate Limit Retry Logic...")
    provider = OpenAIProvider("gpt-4o-mini")

    call_count = 0

    async def mock_create(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            # Mock 429
            mock_request = Request("POST", "https://api.openai.com/v1/chat/completions")
            mock_response = Response(429, headers={"retry-after": "0.1"}, request=mock_request)
            raise OpenAIRateLimitError("Rate limited", response=mock_response, body=None)

        # Success on 3rd try
        class MockUsage:
            prompt_tokens = 10
            completion_tokens = 10

        class MockChoice:
            def __init__(self) -> None:
                class Msg:
                    content = "Success"

                self.message = Msg()
                self.finish_reason = "stop"

        class MockResp:
            choices = [MockChoice()]
            usage = MockUsage()

        return MockResp()

    provider.client.chat.completions.create = AsyncMock(side_effect=mock_create)  # type: ignore

    start = time.time()
    result = await provider.complete([ChatMessage(role="user", content="test")])
    duration = time.time() - start

    assert call_count == 3
    assert duration >= 0.2  # Two retries of 0.1s
    assert result.content == "Success"
    print(f"Ã¢Å“â€¦ Rate limit caught, retried correctly. Took {duration:.2f}s")


async def test_router_vision() -> None:
    print("Testing ModelRouter vision queries...")
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    router = ModelRouter(mock_redis)

    criteria = RoutingCriteria(task_type="classification", require_vision=True)
    chain = await router.route(criteria)
    provider, model = chain[0]
    print(f"Vision model selected: {model}")
    assert "gpt-4o" in model or "claude" in model
    print("Ã¢Å“â€¦ ModelRouter routes vision correctly.")


async def test_metrics_and_telemetry() -> None:
    print("Testing Redis cost tracking and OpenTelemetry spans...")

    # Setup InMemory exporter to verify Jaeger spans
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    # Force mock client
    client = NeuroFlowClient(redis_client=mock_redis)
    client.router = ModelRouter(mock_redis)

    # Mock provider
    mock_provider = OpenAIProvider("gpt-4o-mini")
    mock_provider.complete = AsyncMock(  # type: ignore
        return_value=GenerationResult(
            content="mock",
            model="gpt-4o-mini",
            input_tokens=100,
            output_tokens=100,
            latency_ms=150.0,
            cost_usd=0.005,
            finish_reason="stop",
        )
    )
    client.providers = {"openai:gpt-4o-mini": mock_provider}

    # Run
    await client.chat(
        [ChatMessage(role="user", content="test")], RoutingCriteria(task_type="classification")
    )

    # Check Redis
    mock_redis.incr.assert_called_with("metrics:model:gpt-4o-mini:calls")
    mock_redis.incrbyfloat.assert_called_with("metrics:model:gpt-4o-mini:cost_usd", 0.005)
    print("Ã¢Å“â€¦ Cost tracking increments Redis counters.")

    # Check Telemetry
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "neuroflow.llm.chat"
    assert span.attributes["model"] == "gpt-4o-mini"  # type: ignore
    assert span.attributes["cost_usd"] == 0.005  # type: ignore
    print("Ã¢Å“â€¦ OpenTelemetry spans properly captured.")


async def main() -> Any:  # noqa: ANN401
    await test_full_interface()
    await test_streaming_mock()
    await test_rate_limit_retry()
    await test_router_vision()
    await test_metrics_and_telemetry()
    print("ALL TESTS PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
