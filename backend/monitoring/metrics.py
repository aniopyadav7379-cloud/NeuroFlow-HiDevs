"""
Custom Prometheus metrics. Exposed at GET /metrics (backend/main.py,
already wired to prometheus_client.generate_latest() since Task 32).

Every metric here is a module-level singleton, imported and updated from
wherever the relevant operation actually happens — this module only
DEFINES metrics, it never updates them itself (that would mean the
numbers are fake/synthetic rather than reflecting real system behavior).
See each metric's call sites: backend/providers/client.py (llm_calls,
llm_cost), backend/resilience/circuit_breaker.py (circuit_breaker_trips,
active_circuit_breakers_open), pipelines/ingestion/pipeline.py
(ingestion_docs_total), pipelines/retrieval/*.py (retrieval_latency),
pipelines/generation/generator.py (generation_latency, queries_total),
evaluation/judge.py (eval_faithfulness, eval_overall).
"""
from prometheus_client import Counter, Gauge, Histogram

# ── Counters ─────────────────────────────────────────────────────────
queries_total = Counter("neuroflow_queries_total", "Total queries", ["pipeline_id", "status"])
ingestion_docs_total = Counter("neuroflow_ingestion_docs_total", "Documents ingested", ["source_type"])
llm_calls_total = Counter("neuroflow_llm_calls_total", "LLM API calls", ["provider", "model", "task_type"])
circuit_breaker_trips = Counter("neuroflow_circuit_breaker_trips_total", "Circuit breaker openings", ["provider"])

# ── Histograms ───────────────────────────────────────────────────────
retrieval_latency = Histogram(
    "neuroflow_retrieval_latency_seconds", "Retrieval latency", ["strategy"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)
generation_latency = Histogram(
    "neuroflow_generation_latency_seconds", "Generation latency", ["model"],
    buckets=[0.5, 1, 2, 5, 10, 30],
)
llm_cost = Histogram(
    "neuroflow_llm_cost_usd", "LLM call cost in USD", ["model"],
    buckets=[0.0001, 0.001, 0.01, 0.1, 1.0],
)

# ── Gauges ───────────────────────────────────────────────────────────
eval_faithfulness = Gauge("neuroflow_eval_faithfulness", "Rolling avg faithfulness", ["pipeline_id"])
eval_overall = Gauge("neuroflow_eval_overall", "Rolling avg overall score", ["pipeline_id"])
queue_depth = Gauge("neuroflow_queue_depth", "Ingestion queue depth")
active_circuit_breakers_open = Gauge("neuroflow_circuit_breakers_open", "Number of open circuit breakers")
