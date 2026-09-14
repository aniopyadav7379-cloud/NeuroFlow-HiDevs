"""
ModelRouter — selects a provider+model given RoutingCriteria.

Implements the routing rules from docs/adr/004-model-routing.md at the
provider layer: this is the mechanism ADR 004's tier matrix (A/B/C/F)
compiles down to. The router itself is deliberately dumb — it doesn't
call any LLM, it just picks a model config out of a registry.

Model registry: read from Redis key `router:models`, a JSON list of
ModelConfig-shaped dicts. That key is written to whenever a fine-tuning
job completes and promotes a model (docs/architecture.md §5) — the router
always reads it fresh (no local caching) so a promotion takes effect on
the very next routing decision, with no restart required.
"""
import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger("neuroflow.providers.router")

REDIS_MODELS_KEY = "router:models"

#: task types that must never be routed to a fine-tuned model, regardless
#: of prefer_fine_tuned — a judge scoring generations needs to stay a
#: fixed, capable, un-drifting reference point (see ADR 003's discussion
#: of judge-model versioning).
NO_FINE_TUNE_TASK_TYPES = {"evaluation"}

#: threshold, in tokens, above which "long context" routing applies.
LONG_CONTEXT_THRESHOLD = 100_000


@dataclass
class RoutingCriteria:
    task_type: str  # "rag_generation" | "evaluation" | "embedding" | "classification"
    max_cost_per_call: float | None = None
    require_vision: bool = False
    require_long_context: bool = False  # > 32k tokens needed for the call
    latency_budget_ms: int | None = None
    prefer_fine_tuned: bool = False
    # Rough token estimates for the max_cost_per_call check — the router
    # doesn't know the actual prompt yet at selection time, so callers pass
    # their best estimate (defaults are conservative for a RAG call).
    estimated_input_tokens: int = 2000
    estimated_output_tokens: int = 500


@dataclass
class ModelConfig:
    model: str
    provider: str  # "openai" | "anthropic" | ...
    task_types: list[str] = field(default_factory=list)
    vision: bool = False
    context_window: int = 128_000
    cost_per_input_token: float = 0.0
    cost_per_output_token: float = 0.0
    avg_latency_ms: int = 1500
    fine_tuned: bool = False
    fine_tuned_task_type: str | None = None  # which task_type this fine-tune targets

    def estimated_cost(self, input_tokens: int, output_tokens: int) -> float:
        return input_tokens * self.cost_per_input_token + output_tokens * self.cost_per_output_token


# Bootstrap registry, used only if Redis has nothing registered yet (fresh
# environment, before any fine-tune has been promoted). Mirrors the price
# tables in openai_provider.py / anthropic_provider.py.
DEFAULT_MODELS: list[ModelConfig] = [
    ModelConfig(
        model="gpt-4o-mini", provider="openai",
        task_types=[
            "rag_generation", "classification", "embedding", "image_description",
            "query_expansion", "query_classification", "reranking", "hyde",
        ],
        vision=True, context_window=128_000,
        cost_per_input_token=0.15 / 1_000_000, cost_per_output_token=0.60 / 1_000_000,
        avg_latency_ms=800,
    ),
    ModelConfig(
        model="gpt-4o", provider="openai",
        task_types=["rag_generation", "evaluation", "classification", "image_description", "hyde"],
        vision=True, context_window=128_000,
        cost_per_input_token=2.50 / 1_000_000, cost_per_output_token=10.00 / 1_000_000,
        avg_latency_ms=2000,
    ),
    ModelConfig(
        model="claude-haiku-4-5-20251001", provider="anthropic",
        task_types=[
            "rag_generation", "classification",
            "query_expansion", "query_classification", "reranking", "hyde",
        ],
        vision=False, context_window=200_000,
        cost_per_input_token=0.80 / 1_000_000, cost_per_output_token=4.00 / 1_000_000,
        avg_latency_ms=900,
    ),
    ModelConfig(
        model="claude-sonnet-5", provider="anthropic",
        task_types=["rag_generation", "evaluation", "image_description"],
        vision=True, context_window=200_000,
        cost_per_input_token=3.00 / 1_000_000, cost_per_output_token=15.00 / 1_000_000,
        avg_latency_ms=1800,
    ),
]


class NoModelSatisfiesCriteria(Exception):
    pass


class ModelRouter:
    def __init__(self, redis_client):
        self._redis = redis_client

    async def _load_registry(self) -> list[ModelConfig]:
        raw = await self._redis.get(REDIS_MODELS_KEY)
        if not raw:
            logger.info("router:models not set in Redis, using DEFAULT_MODELS bootstrap registry")
            return list(DEFAULT_MODELS)
        try:
            entries = json.loads(raw)
            return [ModelConfig(**entry) for entry in entries]
        except (json.JSONDecodeError, TypeError) as e:
            logger.error("router:models is malformed (%s), falling back to DEFAULT_MODELS", e)
            return list(DEFAULT_MODELS)

    async def select_model(self, criteria: RoutingCriteria) -> ModelConfig:
        registry = await self._load_registry()

        candidates = [m for m in registry if criteria.task_type in m.task_types]
        if not candidates:
            raise NoModelSatisfiesCriteria(
                f"no registered model supports task_type={criteria.task_type!r}"
            )

        # Rule: evaluation task_type never uses a fine-tuned model, no
        # matter what prefer_fine_tuned says — the judge must stay a fixed
        # reference point (ADR 003).
        if criteria.task_type in NO_FINE_TUNE_TASK_TYPES:
            candidates = [m for m in candidates if not m.fine_tuned]
            if not candidates:
                raise NoModelSatisfiesCriteria(
                    f"no non-fine-tuned model registered for task_type={criteria.task_type!r}"
                )

        # Rule: vision requirement is a hard filter.
        if criteria.require_vision:
            candidates = [m for m in candidates if m.vision]
            if not candidates:
                raise NoModelSatisfiesCriteria("no vision-capable model satisfies the remaining criteria")

        # Rule: long context requirement is a hard filter (>100k tokens).
        if criteria.require_long_context:
            candidates = [m for m in candidates if m.context_window > LONG_CONTEXT_THRESHOLD]
            if not candidates:
                raise NoModelSatisfiesCriteria("no model with >100k context satisfies the remaining criteria")

        # Rule: prefer_fine_tuned — if a fine-tuned model is registered for
        # this task_type (and we're not in the no-fine-tune list above),
        # route to it directly, skipping the cost/latency comparison below.
        if criteria.prefer_fine_tuned and criteria.task_type not in NO_FINE_TUNE_TASK_TYPES:
            fine_tuned_matches = [
                m for m in candidates
                if m.fine_tuned and m.fine_tuned_task_type == criteria.task_type
            ]
            if fine_tuned_matches:
                chosen = min(fine_tuned_matches, key=lambda m: m.avg_latency_ms)
                logger.info("routed task_type=%s to fine-tuned model=%s", criteria.task_type, chosen.model)
                return chosen

        # Rule: latency budget is a hard filter, applied before cost.
        if criteria.latency_budget_ms is not None:
            candidates = [m for m in candidates if m.avg_latency_ms <= criteria.latency_budget_ms]
            if not candidates:
                raise NoModelSatisfiesCriteria(
                    f"no model meets latency_budget_ms={criteria.latency_budget_ms}"
                )

        # Rule: max_cost_per_call filters out models that would exceed it
        # for the estimated call size.
        if criteria.max_cost_per_call is not None:
            candidates = [
                m for m in candidates
                if m.estimated_cost(criteria.estimated_input_tokens, criteria.estimated_output_tokens)
                <= criteria.max_cost_per_call
            ]
            if not candidates:
                raise NoModelSatisfiesCriteria(
                    f"no model fits max_cost_per_call={criteria.max_cost_per_call} "
                    f"for ~{criteria.estimated_input_tokens}in/{criteria.estimated_output_tokens}out tokens"
                )

        # Default: cheapest model (by estimated cost for this call) among
        # everything that survived the hard constraints above.
        chosen = min(
            candidates,
            key=lambda m: m.estimated_cost(criteria.estimated_input_tokens, criteria.estimated_output_tokens),
        )
        logger.info("routed task_type=%s to model=%s (cheapest satisfying constraints)", criteria.task_type, chosen.model)
        return chosen
