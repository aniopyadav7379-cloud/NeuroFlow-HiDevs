import json
from dataclasses import dataclass

from redis.asyncio import Redis


@dataclass
class RoutingCriteria:
    task_type: str  # "rag_generation" | "evaluation" | "embedding" | "classification"
    max_cost_per_call: float | None = None
    require_vision: bool = False
    require_long_context: bool = False  # > 32k tokens in prompt, rule says route to > 100k
    latency_budget_ms: int | None = None
    prefer_fine_tuned: bool = False


@dataclass
class ModelConfig:
    model_name: str
    provider: str
    vision: bool
    context_window: int
    input_cost_per_m: float
    output_cost_per_m: float
    is_judge: bool
    fine_tuned_version: str | None = None
    fine_tuned_task: str | None = None


class ModelRouter:
    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client
        self.cache_key = "router:models"

        # Default fallback models if Redis is empty
        self.default_models = [
            ModelConfig("gpt-4o", "openai", True, 128000, 2.50, 10.00, True),
            ModelConfig("gpt-4o-mini", "openai", True, 128000, 0.15, 0.60, False),
            ModelConfig("claude-3-5-sonnet-20240620", "anthropic", True, 200000, 3.00, 15.00, True),
            ModelConfig("claude-3-haiku-20240307", "anthropic", True, 200000, 0.25, 1.25, False),
        ]

    async def _get_registered_models(self) -> list[ModelConfig]:
        data = await self.redis.get(self.cache_key)
        if not data:
            return self.default_models

        try:
            parsed = json.loads(data)
            return [ModelConfig(**m) for m in parsed]
        except (json.JSONDecodeError, TypeError):
            return self.default_models

    def _estimate_cost(self, model: ModelConfig) -> float:
        # Estimate based on 1k input and 1k output tokens
        return (1000 * model.input_cost_per_m + 1000 * model.output_cost_per_m) / 1_000_000

    async def route(self, criteria: RoutingCriteria) -> list[tuple[str, str]]:
        """
        Returns a fallback chain of [(provider_name, model_name)] matching the criteria,
        ordered from most preferred (cheapest/fine-tuned) to least preferred.
        """
        models = await self._get_registered_models()

        # Rule 4: If task_type="evaluation" -> always use a capable judge model, never fine-tuned
        if criteria.task_type == "evaluation":
            models = [m for m in models if m.is_judge]
            criteria.prefer_fine_tuned = False  # Override

        valid_models = []
        for m in models:
            # Rule 1: If require_vision=True -> route to a vision-capable model
            if criteria.require_vision and not m.vision:
                continue

            # Rule 2: If require_long_context=True -> route to a model with >100k context
            if criteria.require_long_context and m.context_window <= 100000:
                continue

            # Rule 5: If max_cost_per_call is set -> filter out models that would exceed it
            if criteria.max_cost_per_call is not None:
                if self._estimate_cost(m) > criteria.max_cost_per_call:
                    continue

            valid_models.append(m)

        if not valid_models:
            raise ValueError(f"No models satisfy the hard constraints: {criteria}")

        chain = []
        # Rule 3: If prefer_fine_tuned=True AND a fine-tuned model is registered for this task_type -> route to it  # noqa: E501
        if criteria.prefer_fine_tuned:
            for m in valid_models:
                if m.fine_tuned_version and m.fine_tuned_task == criteria.task_type:
                    chain.append((m.provider, m.fine_tuned_version))

        # Rule 6: Default -> route to the cheapest model that satisfies all hard constraints
        # Sort by total estimated cost
        valid_models.sort(key=lambda m: self._estimate_cost(m))
        for m in valid_models:
            chain.append((m.provider, m.model_name))

        return chain
