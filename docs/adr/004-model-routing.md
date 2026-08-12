# ADR 004: Model Routing — how NeuroFlow picks a model per query

## Context

The Generation Subsystem routes every query to one of several model tiers (`architecture.md` §3), and the Fine-Tuning Subsystem eventually adds fine-tuned models into that same routing decision once they're promoted (`architecture.md` §5). Routing needs to balance four signals that often conflict: **cost**, **latency**, **capability** (does the model actually handle this query type well), and **domain** (some domains have a fine-tuned specialist once one is promoted). This becomes the implementation spec for Task 38.

## Decision

Route on a **tiered matrix**, evaluated in this order: fine-tuned specialist availability → domain → query complexity → cost/latency budget.

### Model tiers

| Tier | Profile | Example use |
|---|---|---|
| **A — Fast/cheap** | Low latency, low cost, weaker on multi-step reasoning | Simple factual lookups, short context windows, high query volume |
| **B — Balanced** | Mid cost/latency, solid general reasoning | Default tier — most queries land here |
| **C — Frontier** | Highest cost/latency, strongest reasoning and instruction-following | Complex multi-hop questions, long context, high-stakes domains |
| **F — Fine-tuned specialist** | Domain-tuned, cost similar to its base tier | Only used once promoted (ADR 003 promotion gate) for its specific domain |

### Routing matrix — which tier wins for which query type

| Query characteristic | Tier chosen | Why |
|---|---|---|
| Domain has a **promoted** fine-tuned model and query matches that domain | **F** | Domain-tuned model has already beaten base model's eval scores on this domain (ADR 003 shadow-eval gate) |
| Short, single-fact query, small context window, no multi-hop reasoning | **A** | Capability sufficient; cost/latency dominate the decision |
| High query volume path (e.g. autocomplete-style or bulk batch queries) | **A** | Throughput and cost dominate; occasional lower answer quality is acceptable for this use case |
| General query, moderate context window (default case) | **B** | Best cost/capability balance; this is the default when no other row matches |
| Long context window (near the pipeline's `context_window_size` ceiling) or multi-hop reasoning across several chunks | **C** | Capability requirement outweighs cost — cheaper tiers show measurably lower faithfulness on multi-hop synthesis |
| High-stakes domain (e.g. compliance, legal, medical-adjacent) without a promoted fine-tuned specialist yet | **C** | Faithfulness risk tolerance is lower; pay for the strongest general model until a specialist is promoted |
| Latency SLA is explicitly tight (e.g. `stream=true` interactive UI with a p95 target) and query is not high-stakes/multi-hop | **A** or **B** | Latency budget caps tier even if C would nominally give better quality; router picks the highest tier that still meets the SLA |
| Cost budget for the pipeline/caller is capped (per `pipelines.retrieval_config` / caller plan) | Highest tier affordable within budget, floor at **A** | Cost ceiling is a hard constraint, not a preference |

### Decision procedure (pseudocode)

```
route(query, pipeline, caller_budget, sla_ms):
    if pipeline.domain has promoted fine_tuned_model:
        return Tier.F

    complexity = estimate_complexity(query, context_window)  # multi-hop? long context?
    is_high_stakes = pipeline.domain in HIGH_STAKES_DOMAINS

    if complexity == high or is_high_stakes:
        candidate = Tier.C
    elif complexity == low and pipeline.high_volume_path:
        candidate = Tier.A
    else:
        candidate = Tier.B

    # latency and cost are hard caps, applied after capability selection
    candidate = min(candidate, max_tier_within_latency(sla_ms))
    candidate = min(candidate, max_tier_within_budget(caller_budget))
    return candidate
```

Every routing decision is logged to `generations.routing_reason` (`data-models.md`) with the signals that drove it (domain match, complexity estimate, SLA cap, budget cap) so routing behavior is auditable and mining/evaluation can break down quality by *why* a tier was chosen, not just which tier was chosen.

## Consequences

- **Positive:** routing is deterministic and explainable, degrades gracefully under cost/latency pressure (caps are applied after capability selection, not instead of it), and has a clear on-ramp for fine-tuned models to take over specific domains as they're promoted.
- **Negative:** `estimate_complexity` and `HIGH_STAKES_DOMAINS` are themselves judgment calls that need their own tuning and review — a miscalibrated complexity estimator could under-route hard queries to Tier A and silently hurt faithfulness. This is caught downstream by the Evaluation Subsystem: faithfulness aggregates broken out by tier (ADR 003) are the feedback signal for retuning the complexity estimator.
- **Follow-up (Task 38 scope):** implement `estimate_complexity`, the `HIGH_STAKES_DOMAINS` config, and the budget/SLA cap functions as concrete, testable units against this pseudocode contract.
