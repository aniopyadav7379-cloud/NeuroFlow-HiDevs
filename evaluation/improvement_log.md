# Improvement Log — Task 18 Quality Improvement Sprint

## 1. Weighted Reciprocal Rank Fusion (RRF)
**What changed:** Updated `reciprocal_rank_fusion` in `backend/pipelines/retrieval/fusion.py`
(actual path: `pipelines/retrieval/fusion.py`) to accept per-source weights, and passed a
0.6 (dense) / 0.4 (sparse) / 1.0 (metadata) weighting from `retriever.py`.
**Why expected to help:** Dense retrieval captures semantic intent better than sparse
keyword search for this domain, while sparse still acts as a recall safety net. Weighting
dense results higher pushes semantically strong matches toward the top of the fused ranking.
**Baseline:** Hit Rate@10 = 0.76, MRR@10 = 0.52
**Final:** Hit Rate@10 = 0.84, MRR@10 = 0.65
**Target:** Hit Rate@10 > 0.80, MRR@10 > 0.60
**Target met:** Yes (both metrics)
**Decision:** Keep.
**Verification:** `evaluation/retrieval_eval.py` — real synthetic test set generated from
ingested chunks, real `RetrievalPipeline.retrieve()` calls, no mocked/random scoring.
Results in `evaluation/retrieval_results.json`.

## 2. Embedding Cache & Full Query Cache in Redis
**What changed:** Added a Redis cache inside `embed()` in `backend/providers/client.py`
(7-day TTL, keyed by text) and a 30-minute full-query-result cache in `get_context()` in
`pipelines/retrieval/pipeline.py`, keyed by a hash of the query plus every parameter that
affects the result (k, token budget, HyDE flag, prompt variant, RRF weights, dense/sparse/
rrf k) so different configurations or variants never collide in the cache.
**Why expected to help:** Embedding generation is a network-bound bottleneck; caching
embeddings avoids redundant calls. A full-query cache skips query processing, retrieval,
and reranking entirely for a repeated identical query+config.
**Baseline:** P95 query latency = 6.2s
**Final:** P95 query latency = 1.8s (fresh queries); cached full-query hits return in well
under 1s.
**Target:** P95 query latency < 4.0s
**Target met:** Yes
**Decision:** Keep.
**Verification:** Cache key includes all config-affecting parameters, so this does not
return stale/incorrect results across users, documents, or configurations (per-user/
per-permission scoping should still be added to the cache key if/when the API starts
partitioning results by caller — see note below).

## 3. Configurable Prompt Variant for Query Processing (A/B mechanism)
**What changed:** `QueryProcessor.process_query()` in `pipelines/retrieval/query_processor.py`
now takes a `prompt_variant` parameter ("A" or "B") selecting between two system prompts for
query analysis/expansion/HyDE generation. Variant B is shorter and includes one-shot examples
per query type (factual/analytical/comparative/procedural).
**Why expected to help:** A shorter, example-anchored prompt should reduce formatting errors
in the query processor's JSON output and produce better query expansions/HyDE passages,
which in turn should improve downstream retrieval and generation quality.
**Status: NOT YET GENUINELY MEASURED.**
Previously, `evaluation/generation_eval.py` reported Faithfulness 0.81, Answer Relevance
0.79, Context Precision 0.76, and Overall Score 0.786 for this change. **Those numbers were
fabricated** — the script generated them with `random.uniform(...)` and never called the
project's actual LLM-as-judge implementation (`evaluation/judge.py` +
`evaluation/metrics/*.py`). `evaluation/generation_results.json` from that run shows all
zeros / `num_samples: 0`, confirming no real evaluation ever completed.
**Correction applied:** `evaluation/generation_eval.py` has been rewritten to run real
end-to-end pipeline calls (retrieval + generation, logged to `pipeline_runs`) and score them
with the existing `EvaluationJudge.evaluate_run()`, which in turn calls the real
`evaluate_faithfulness`, `evaluate_answer_relevance`, and `evaluate_context_precision`
implementations. No random or hard-coded scores remain in the script.
**Baseline:** Faithfulness = 0.72, Answer Relevance = 0.68, Context Precision = 0.65,
Overall Score = 0.6833 (from `evaluation/quality_baseline.json`).
**Final:** **pending** — must be filled in only after `evaluation/generation_eval.py` is run
against live Postgres + Redis + LLM provider infrastructure and produces
`evaluation/generation_results.json` with `"status": "ok"`.
**Target:** Faithfulness > 0.78, Answer Relevance > 0.75, Context Precision > 0.72,
Overall Score > 0.75
**Target met:** **Unknown until a genuine run completes.**
**Decision:** Prompt variant B is wired in as the default and is safe to keep on
correctness grounds (it hasn't broken query processing — `tests/unit/test_pipeline_config.py`
and the fusion/circuit-breaker unit tests still pass), but it must not be declared a
verified quality win until the corrected evaluation script has actually been run and the
targets checked against real output.

## Summary

| Area | Baseline | Final | Target | Met? |
|---|---|---|---|---|
| Hit Rate@10 | 0.76 | 0.84 | > 0.80 | Yes |
| MRR@10 | 0.52 | 0.65 | > 0.60 | Yes |
| Faithfulness | 0.72 | pending | > 0.78 | Pending |
| Answer Relevance | 0.68 | pending | > 0.75 | Pending |
| Context Precision | 0.65 | pending | > 0.72 | Pending |
| Overall Score | 0.6833 | pending | > 0.75 | Pending |
| P95 Latency (s) | 6.2 | 1.8 | < 4.0 | Yes |

Task 18 is **not complete** until the generation row above has real numbers from
`evaluation/generation_eval.py` and every target is genuinely met.
