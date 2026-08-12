# ADR 003: Evaluation Framework — LLM-as-judge over human annotation only

## Context

Every generation needs to be scored on faithfulness, answer relevance, context precision, and context recall (Evaluation Subsystem, `architecture.md` §4). NeuroFlow also depends on these scores to mine fine-tuning data (`faithfulness > 0.8 AND user_rating >= 4`) and to gate model promotion. The scoring needs to run on every generation, continuously, at production volume — human annotation alone cannot cover that.

## Decision

Use **automated LLM-as-judge evaluation as the primary, always-on scoring mechanism**, with human annotation used narrowly as a calibration and audit layer rather than the primary signal.

- LLM-as-judge runs asynchronously on 100% of generations (Evaluation Subsystem, decoupled via outbox pattern so it never adds latency to the user path).
- A separate judge model (distinct from — and where feasible, higher-capability than — the generation model to reduce self-preference bias) scores each of the four metrics independently, with claim-decomposition for faithfulness rather than a single holistic score.
- Human annotation is used on a **sampled subset** (e.g. a fixed weekly sample plus all `user_rating <= 2` generations) purely to calibrate the judge — comparing human labels to judge scores and adjusting judge prompts/thresholds when they diverge.

## Consequences

**Why not human annotation only:** it cannot scale to per-generation, continuous coverage; latency and cost of human review make it unusable as the live signal driving fine-tune data mining or model promotion gates, both of which need every generation scored, not a sample.

**Failure modes of LLM-as-judge, and detection:**
- **Self-preference bias** — a judge model tends to score outputs from its own model family higher. *Detection:* track average judge scores broken out by generation model, including the judge's own family; a persistent unexplained gap favoring same-family generations is a bias signal, checked during the human-calibration sampling.
- **Judge drift after prompt or model version changes** — updating the judge prompt or swapping the judge model shifts score distributions, making before/after aggregates non-comparable. *Detection:* `judge_model` is stamped on every `evaluations` row (`data-models.md`); rolling aggregates are computed per judge-model version, and a version change triggers a re-baseline window before it's used for promotion gating.
- **Gaming via verbose or hedge-y answers** — judges can be swayed by answer length, confident tone, or hedging language rather than actual correctness. *Detection:* periodic human-calibration sample specifically includes long/verbose outliers and near-boundary scores (e.g. faithfulness in 0.75–0.85) to check whether the judge is anchoring on surface features.
- **Context recall estimation without ground truth** — recall requires knowing what *should* have been retrieved, which isn't always available. *Detection:* recall scores are flagged as "estimated" (vs "reference-based") in the schema when no ground-truth reference exists, and only reference-based recall scores are used for hard promotion gates; estimated scores are directional only.
- **Judge cost/latency at scale** — scoring every generation on 4 dimensions multiplies inference cost. *Mitigation, not a correctness failure mode but a viability one:* judge calls are batched and run on a cheaper model tier where calibration shows acceptable agreement with a stronger judge, with periodic recalibration against the stronger model.

## Consequences (summary)

- **Positive:** every generation is scored, enabling real-time quality aggregates, automated fine-tune data mining, and automated model-promotion gating without waiting on human review.
- **Negative:** judge quality is now a dependency that itself needs monitoring; without the calibration sampling above, systematic judge bias would silently corrupt both the aggregate metrics and the fine-tuning data pipeline that depends on them.
