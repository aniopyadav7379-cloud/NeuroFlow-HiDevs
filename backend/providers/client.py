import threading
from collections.abc import AsyncGenerator
from typing import Any

from opentelemetry import trace
from redis.asyncio import Redis

from backend.resilience.circuit_breaker import CircuitBreaker
from backend.resilience.rate_limiter import consume_llm_token
from backend.resilience.timeout_manager import TimeoutManager

from .anthropic_provider import AnthropicProvider
from .base import BaseLLMProvider, ChatMessage, GenerationResult
from .openai_provider import OpenAIProvider
from .router import ModelRouter, RoutingCriteria

tracer = trace.get_tracer(__name__)


class NeuroFlowClient:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, redis_client: Redis | None = None) -> Any:  # noqa: ANN401
        with cls._lock:
            if cls._instance is None:
                if redis_client is None:
                    raise ValueError("redis_client must be provided on first instantiation")
                cls._instance = super().__new__(cls)
                cls._instance._init(redis_client)
            return cls._instance

    def _init(self, redis_client: Redis) -> Any:  # noqa: ANN401
        self.redis = redis_client
        self.router = ModelRouter(self.redis)
        self.providers: dict[str, BaseLLMProvider] = {}

    def _get_provider(self, provider_name: str, model_name: str) -> BaseLLMProvider:
        key = f"{provider_name}:{model_name}"
        if key not in self.providers:
            if provider_name == "openai":
                self.providers[key] = OpenAIProvider(model_name)
            elif provider_name == "anthropic":
                self.providers[key] = AnthropicProvider(model_name)
            else:
                raise ValueError(f"Unknown provider: {provider_name}")
        return self.providers[key]

    async def _record_metrics(self, result: GenerationResult) -> Any:  # noqa: ANN401
        # Increment calls
        calls_key = f"metrics:model:{result.model}:calls"
        await self.redis.incr(calls_key)

        # Increment cost (Redis float increment)
        cost_key = f"metrics:model:{result.model}:cost_usd"
        await self.redis.incrbyfloat(cost_key, result.cost_usd)

    async def chat(
        self,
        messages: list[ChatMessage],
        criteria: RoutingCriteria,
        **kwargs: Any,  # noqa: ANN401
    ) -> GenerationResult:
        chain = await self.router.route(criteria)

        last_exception = None
        for provider_name, model_name in chain:
            try:
                provider = self._get_provider(provider_name, model_name)

                with tracer.start_as_current_span("neuroflow.llm.chat") as span:
                    span.set_attribute("provider", provider_name)
                    span.set_attribute("model", model_name)

                    # Wait for global LLM token limit
                    await consume_llm_token(provider_name)

                    async with CircuitBreaker(provider_name):
                        result = await TimeoutManager.run(
                            "chat_completion", provider.complete(messages, **kwargs)
                        )

                    # Decorate span with telemetry
                    span.set_attribute("input_tokens", result.input_tokens)
                    span.set_attribute("output_tokens", result.output_tokens)
                    span.set_attribute("cost_usd", result.cost_usd)
                    span.set_attribute("latency_ms", result.latency_ms)

                    # Record metrics in Redis
                    await self._record_metrics(result)

                    return result  # type: ignore
            except Exception as e:
                # Catch non-retryable errors (or exhausted rate limit retries) and fallback
                last_exception = e
                continue

        raise RuntimeError(
            f"All fallback models failed for criteria {criteria}. Last error: {last_exception}"
        ) from last_exception

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        criteria: RoutingCriteria,
        **kwargs: Any,  # noqa: ANN401
    ) -> AsyncGenerator[str, None]:
        chain = await self.router.route(criteria)

        last_exception = None
        for provider_name, model_name in chain:
            try:
                provider = self._get_provider(provider_name, model_name)

                span = tracer.start_span("neuroflow.llm.stream_chat")
                span.set_attribute("provider", provider_name)
                span.set_attribute("model", model_name)

                # Wait for global LLM token limit
                await consume_llm_token(provider_name)

                stream_gen = provider.stream(messages, **kwargs)

                async def _get_first() -> Any:  # noqa: ANN401
                    return await stream_gen.__anext__()  # type: ignore

                # Test connection by fetching the first chunk
                async with CircuitBreaker(provider_name):
                    first_chunk = await TimeoutManager.run("chat_completion", _get_first())

                async def stream_wrapper() -> Any:  # noqa: ANN401
                    with trace.use_span(span, end_on_exit=True):
                        try:
                            yield first_chunk
                            async for chunk in stream_gen:  # type: ignore
                                yield chunk
                        except Exception as e:
                            span.record_exception(e)
                            raise e

                return stream_wrapper()  # type: ignore
            except StopAsyncIteration:
                # Empty stream
                async def empty_stream() -> Any:  # noqa: ANN401
                    yield ""

                return empty_stream()  # type: ignore
            except Exception as e:
                last_exception = e
                continue

        raise RuntimeError(
            f"All fallback stream models failed for criteria {criteria}. Last error: {last_exception}"  # noqa: E501
        ) from last_exception

    async def embed(self, texts: list[str], use_cache: bool = True) -> list[list[float]]:
        import hashlib
        import json

        if not use_cache:
            provider = self._get_provider("openai", "text-embedding-3-small")
            with tracer.start_as_current_span("neuroflow.llm.embed") as span:
                span.set_attribute("provider", "openai")
                span.set_attribute("model", "text-embedding-3-small")
                await consume_llm_token("openai")
                async with CircuitBreaker("openai"):
                    return await TimeoutManager.run("embedding", provider.embed(texts))  # type: ignore

        cached_embeddings = []
        texts_to_embed = []
        indices_to_embed = []

        # 1. Check Redis cache for each text
        for i, text in enumerate(texts):
            key_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            cache_key = f"cache:embed:{key_hash}"
            cached = await self.redis.get(cache_key)
            if cached:
                cached_embeddings.append((i, json.loads(cached)))
            else:
                texts_to_embed.append(text)
                indices_to_embed.append(i)

        final_embeddings: list[list[float] | None] = [None] * len(texts)
        for i, emb in cached_embeddings:
            final_embeddings[i] = emb

        if not texts_to_embed:
            return final_embeddings  # type: ignore

        # 2. Fetch missing embeddings
        provider = self._get_provider("openai", "text-embedding-3-small")

        with tracer.start_as_current_span("neuroflow.llm.embed") as span:
            span.set_attribute("provider", "openai")
            span.set_attribute("model", "text-embedding-3-small")

            await consume_llm_token("openai")

            async with CircuitBreaker("openai"):
                new_embeddings = await TimeoutManager.run(
                    "embedding", provider.embed(texts_to_embed)
                )

            # 3. Store new embeddings in cache
            for i, text in enumerate(texts_to_embed):
                emb = new_embeddings[i]
                original_index = indices_to_embed[i]
                final_embeddings[original_index] = emb

                key_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                cache_key = f"cache:embed:{key_hash}"
                await self.redis.setex(cache_key, 86400 * 7, json.dumps(emb))  # Cache for 7 days

            return final_embeddings  # type: ignore
