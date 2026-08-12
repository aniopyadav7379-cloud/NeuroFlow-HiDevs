"""
NeuroFlowClient — the single entrypoint the rest of the codebase uses to
talk to any LLM. Generation Subsystem, Evaluation Subsystem, and Ingestion
Subsystem's embedder all go through `client.chat(...)` / `client.embed(...)`
— none of them import a provider module directly.

Responsibilities beyond just calling a provider:
  - resolve RoutingCriteria -> a specific provider+model via ModelRouter
  - track per-model call counts and cost in Redis
  - emit an OpenTelemetry span per provider call
  - (optional) run a FallbackChain instead of a single provider/model
"""
import logging
import time
from typing import AsyncGenerator

from opentelemetry import trace

from backend.providers.anthropic_provider import AnthropicProvider
from backend.providers.base import (
    BaseLLMProvider,
    ChatMessage,
    GenerationResult,
    NonRetryableProviderError,
    ProviderError,
    RetryableProviderError,
)
from backend.providers.openai_provider import OpenAIProvider
from backend.providers.router import ModelConfig, ModelRouter, RoutingCriteria
from backend.resilience.circuit_breaker import circuit_breaker
from backend.resilience.rate_limiter import acquire_global_provider_tokens
from backend.resilience.timeout_manager import TimeoutManager
from backend.monitoring.metrics import llm_calls_total, llm_cost

logger = logging.getLogger("neuroflow.providers.client")
tracer = trace.get_tracer("neuroflow.providers")

# Maps RoutingCriteria.task_type -> TimeoutManager bucket (backend/
# resilience/timeout_manager.py's DEFAULT_TIMEOUTS keys) — several
# NeuroFlow task_types share the same "it's a chat completion call"
# timeout budget even though they're routed/priced independently.
_TIMEOUT_TASK_TYPE_MAP = {
    "rag_generation": "chat_completion",
    "hyde": "chat_completion",
    "query_expansion": "chat_completion",
    "query_classification": "chat_completion",
    "image_description": "chat_completion",
    "classification": "chat_completion",
    "evaluation": "evaluation",
    "reranking": "reranking",
    "embedding": "embedding",
}


def _timeout_bucket(task_type: str) -> str:
    return _TIMEOUT_TASK_TYPE_MAP.get(task_type, "chat_completion")


def _calls_key(model: str) -> str:
    return f"metrics:model:{model}:calls"


def _cost_key(model: str) -> str:
    return f"metrics:model:{model}:cost_usd"


class NeuroFlowClient:
    """Not a true process-wide singleton object by itself — call
    get_client() (module-level, below) to get the shared instance rather
    than constructing this directly, so app.state and the worker share one
    set of provider clients and one router."""

    def __init__(self, providers: dict[str, BaseLLMProvider], router: ModelRouter, redis_client):
        self._providers = providers
        self._router = router
        self._redis = redis_client

    @property
    def redis(self):
        """Public accessor for the same Redis client this NeuroFlowClient
        uses internally — lets other modules (e.g. backend/services/
        pipeline_runner.py's per-pipeline rate limiting) share it without
        threading a second redis_client parameter through every call site
        that already has an llm_client."""
        return self._redis

    def _provider_for(self, model_config: ModelConfig) -> BaseLLMProvider:
        provider = self._providers.get(model_config.provider)
        if provider is None:
            raise NonRetryableProviderError(f"no provider registered for '{model_config.provider}'")
        return provider

    async def _record_metrics(self, model: str, cost_usd: float) -> None:
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(_calls_key(model))
                pipe.incrbyfloat(_cost_key(model), cost_usd)
                await pipe.execute()
        except Exception:
            # Metrics are best-effort — a Redis blip should never fail an
            # otherwise-successful LLM call.
            logger.exception("failed to record metrics for model=%s", model)

    async def resolve_model(self, routing_criteria: RoutingCriteria) -> ModelConfig:
        """Runs routing without making a call — used by callers that need
        to know the model ahead of time (e.g. pipelines/generation/
        generator.py logs `model_used` before streaming starts). Passing
        the result back in as `model_config=` to chat()/stream() avoids
        routing twice, which could pick a different model if router:models
        changes between the two calls."""
        return await self._router.select_model(routing_criteria)

    async def chat(
        self, messages: list[ChatMessage], routing_criteria: RoutingCriteria,
        *, model_config: ModelConfig | None = None, **kwargs,
    ) -> GenerationResult:
        model_config = model_config or await self._router.select_model(routing_criteria)
        provider = self._provider_for(model_config)

        await acquire_global_provider_tokens(self._redis, model_config.provider)
        timeout_manager = TimeoutManager(self._redis)
        cb = circuit_breaker(model_config.provider, self._redis)

        with tracer.start_as_current_span("neuroflow.provider.chat") as span:
            span.set_attribute("model", model_config.model)
            span.set_attribute("provider", model_config.provider)
            span.set_attribute("task_type", routing_criteria.task_type)

            started = time.perf_counter()
            async with cb:
                result = await timeout_manager.run(
                    _timeout_bucket(routing_criteria.task_type),
                    provider.complete(messages, model=model_config.model, **kwargs),
                )
            span.set_attribute("input_tokens", result.input_tokens)
            span.set_attribute("output_tokens", result.output_tokens)
            span.set_attribute("cost_usd", result.cost_usd)
            span.set_attribute("latency_ms", result.latency_ms)

        llm_calls_total.labels(provider=model_config.provider, model=model_config.model, task_type=routing_criteria.task_type).inc()
        llm_cost.labels(model=model_config.model).observe(result.cost_usd)
        await self._record_metrics(model_config.model, result.cost_usd)
        return result

    async def stream(
        self, messages: list[ChatMessage], routing_criteria: RoutingCriteria,
        *, model_config: ModelConfig | None = None, **kwargs,
    ) -> AsyncGenerator[str, None]:
        model_config = model_config or await self._router.select_model(routing_criteria)
        provider = self._provider_for(model_config)

        await acquire_global_provider_tokens(self._redis, model_config.provider)
        timeout_manager = TimeoutManager(self._redis)
        cb = circuit_breaker(model_config.provider, self._redis)
        timeout_bucket = _timeout_bucket(routing_criteria.task_type)

        with tracer.start_as_current_span("neuroflow.provider.stream") as span:
            span.set_attribute("model", model_config.model)
            span.set_attribute("provider", model_config.provider)
            span.set_attribute("task_type", routing_criteria.task_type)

            started = time.perf_counter()
            token_count = 0
            # Circuit breaker wraps the whole stream's lifetime (opens on
            # any exception during iteration, closes on clean completion —
            # `async with` around `yield` is valid in an async generator
            # and __aexit__ still runs on close()/throw()). Each individual
            # __anext__() gets its own timeout so a provider that goes
            # silent mid-stream is caught as a stall, not an infinite wait,
            # without capping the total length of a long generation.
            async with cb:
                agen = provider.stream(messages, model=model_config.model, **kwargs).__aiter__()
                while True:
                    try:
                        token = await timeout_manager.run(timeout_bucket, agen.__anext__())
                    except StopAsyncIteration:
                        break
                    token_count += 1
                    yield token

            span.set_attribute("output_token_chunks", token_count)
            span.set_attribute("latency_ms", (time.perf_counter() - started) * 1000)

        # Streaming responses don't return a GenerationResult with exact
        # usage/cost until the caller separately logs the completed
        # generation (Generation Subsystem writes to `generations` with
        # the full record once the stream finishes) — metrics here are
        # call-count only; cost is recorded by the caller from that log.
        await self._record_metrics(model_config.model, 0.0)

    async def embed(self, texts: list[str], routing_criteria: RoutingCriteria | None = None) -> list[list[float]]:
        criteria = routing_criteria or RoutingCriteria(task_type="embedding")
        model_config = await self._router.select_model(criteria)
        provider = self._provider_for(model_config)

        await acquire_global_provider_tokens(self._redis, model_config.provider)
        timeout_manager = TimeoutManager(self._redis)
        cb = circuit_breaker(model_config.provider, self._redis)

        with tracer.start_as_current_span("neuroflow.provider.embed") as span:
            span.set_attribute("model", model_config.model)
            span.set_attribute("provider", model_config.provider)
            span.set_attribute("batch_size", len(texts))

            async with cb:
                vectors = await timeout_manager.run(
                    "embedding", provider.embed(texts, model=model_config.model)
                )

        await self._record_metrics(model_config.model, 0.0)
        return vectors


class FallbackChain:
    """Tries a fixed, ordered list of (provider_name, model) pairs. Moves
    to the next pair on ANY ProviderError from the current one (both
    NonRetryableProviderError, and RetryableProviderError — which only
    surfaces after the provider's own internal retry budget is already
    exhausted, so there's nothing left to gain from retrying the same
    provider again here).

    Example: FallbackChain(client, [("openai", "gpt-4o-mini"),
                                     ("anthropic", "claude-haiku-4-5-20251001"),
                                     ("openai", "gpt-4o")])
    """

    def __init__(self, client: NeuroFlowClient, chain: list[tuple[str, str]]):
        if not chain:
            raise ValueError("FallbackChain requires at least one (provider_name, model) pair")
        self._client = client
        self._chain = chain

    async def chat(self, messages: list[ChatMessage], **kwargs) -> GenerationResult:
        last_error: ProviderError | None = None

        for provider_name, model in self._chain:
            provider = self._client._providers.get(provider_name)
            if provider is None:
                logger.warning("FallbackChain: no provider registered for '%s', skipping", provider_name)
                continue

            with tracer.start_as_current_span("neuroflow.provider.chat.fallback_attempt") as span:
                span.set_attribute("model", model)
                span.set_attribute("provider", provider_name)
                try:
                    result = await provider.complete(messages, model=model, **kwargs)
                    span.set_attribute("cost_usd", result.cost_usd)
                    await self._client._record_metrics(model, result.cost_usd)
                    return result
                except ProviderError as e:
                    span.set_attribute("error", str(e))
                    logger.warning("FallbackChain: %s/%s failed (%s), trying next", provider_name, model, e)
                    last_error = e
                    continue

        raise last_error or ProviderError("FallbackChain exhausted with no configured providers")


# ── module-level singleton wiring ──────────────────────────────────────
_client_instance: NeuroFlowClient | None = None


def build_client(settings, redis_client) -> NeuroFlowClient:
    """Construct the process-wide NeuroFlowClient. Call once, from the
    lifespan handler (API) or worker startup, and reuse via get_client()
    everywhere else."""
    global _client_instance

    providers: dict[str, BaseLLMProvider] = {}
    if getattr(settings, "openai_api_key", None):
        providers["openai"] = OpenAIProvider(api_key=settings.openai_api_key)
    if getattr(settings, "anthropic_api_key", None):
        providers["anthropic"] = AnthropicProvider(api_key=settings.anthropic_api_key)

    if not providers:
        raise RuntimeError(
            "no LLM provider API keys configured — set OPENAI_API_KEY and/or "
            "ANTHROPIC_API_KEY (see backend/config.py)"
        )

    router = ModelRouter(redis_client)
    _client_instance = NeuroFlowClient(providers=providers, router=router, redis_client=redis_client)
    return _client_instance


def get_client() -> NeuroFlowClient:
    if _client_instance is None:
        raise RuntimeError("NeuroFlowClient not initialized — call build_client() at startup first")
    return _client_instance
