"""
Model registration: after a fine-tuning job succeeds, add the new model
to Redis' `router:models` registry (backend/providers/router.py reads
this fresh on every routing decision — see router.py's module docstring —
so this takes effect on the very next query, no restart needed).
"""
import json
import logging

from backend.providers.router import DEFAULT_MODELS, REDIS_MODELS_KEY

logger = logging.getLogger("neuroflow.finetuning.registration")


async def register_finetuned_model(
    redis_client, *, base_model: str, fine_tuned_model_name: str, target_task_type: str
) -> None:
    raw = await redis_client.get(REDIS_MODELS_KEY)
    if raw:
        try:
            registry: list[dict] = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("router:models was malformed, rebuilding from DEFAULT_MODELS before registering")
            registry = [vars(m) for m in DEFAULT_MODELS]
    else:
        registry = [vars(m) for m in DEFAULT_MODELS]

    # Base the new entry on the base model's own config (same pricing
    # tier, context window, vision support) — only the identity and
    # fine-tuned-specific fields change.
    base_entry = next((m for m in registry if m.get("model") == base_model), None)
    new_entry = dict(base_entry) if base_entry else {
        "model": fine_tuned_model_name, "provider": "openai", "task_types": [],
        "vision": False, "context_window": 128_000,
        "cost_per_input_token": 0.0, "cost_per_output_token": 0.0, "avg_latency_ms": 1500,
    }
    new_entry.update({
        "model": fine_tuned_model_name,
        "task_types": [target_task_type],
        "fine_tuned": True,
        "fine_tuned_task_type": target_task_type,
    })

    # Idempotency: if this exact model name is already registered (e.g. a
    # retry of the same job's poll), replace rather than duplicate it.
    registry = [m for m in registry if m.get("model") != fine_tuned_model_name]
    registry.append(new_entry)

    await redis_client.set(REDIS_MODELS_KEY, json.dumps(registry))
    logger.info(
        "registered fine-tuned model=%s for task_type=%s (base_model=%s)",
        fine_tuned_model_name, target_task_type, base_model,
    )
