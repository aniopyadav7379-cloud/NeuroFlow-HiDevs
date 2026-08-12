"""
Retrieval benchmark: expands Task 35's evaluation to compare dense-only,
sparse-only, hybrid (RRF), and hybrid+reranked across Hit Rate@5,
Hit Rate@10, MRR@10, and NDCG@10.

NOT runnable to produce real numbers here — needs a live Postgres with a
real ingested corpus and real embeddings/LLM credentials, none of which
this sandboxed environment has (same constraint as Task 35's
evaluation/retrieval_eval.py and Task 39's calibration harness — see
those for the established pattern this follows).

tests/benchmarks/golden_set.json is a TEMPLATE (3 example rows; the task
calls for 50) with placeholder relevant_chunk_ids — this script refuses
to run until they're replaced with real chunk IDs from your corpus.

Usage:
    python -m tests.benchmarks.retrieval_benchmark
"""
import asyncio
import json
import logging
import math
import sys
from pathlib import Path

from backend.config import get_settings
from backend.db.pool import create_pool, close_pool
from backend.providers.client import build_client
from pipelines.retrieval.pipeline import RetrievalPipeline
from pipelines.retrieval.reranker import APIRerankerScorer, rerank

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("neuroflow.benchmarks.retrieval")

GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.json"
RESULTS_PATH = Path(__file__).parent / "retrieval_benchmark_results.md"

REQUIRED_MRR_IMPROVEMENT_PCT = 15.0  # hybrid+reranked must beat dense-only by >= this on MRR@10


def hit_rate_at_k(results: list, relevant_ids: set, k: int) -> bool:
    return any(r.chunk_id in relevant_ids for r in results[:k])


def reciprocal_rank_at_k(results: list, relevant_ids: set, k: int) -> float:
    for i, r in enumerate(results[:k], start=1):
        if r.chunk_id in relevant_ids:
            return 1.0 / i
    return 0.0


def ndcg_at_k(results: list, relevant_ids: set, k: int) -> float:
    dcg = sum(
        (1.0 / math.log2(i + 1)) for i, r in enumerate(results[:k], start=1) if r.chunk_id in relevant_ids
    )
    ideal_hits = min(len(relevant_ids), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


def aggregate(per_query: list[dict]) -> dict:
    n = len(per_query)
    if n == 0:
        return {"hit_rate@5": 0.0, "hit_rate@10": 0.0, "mrr@10": 0.0, "ndcg@10": 0.0}
    return {
        "hit_rate@5": sum(q["hit@5"] for q in per_query) / n,
        "hit_rate@10": sum(q["hit@10"] for q in per_query) / n,
        "mrr@10": sum(q["rr@10"] for q in per_query) / n,
        "ndcg@10": sum(q["ndcg@10"] for q in per_query) / n,
    }


async def run_condition(pipeline: RetrievalPipeline, golden_set: list[dict], mode: str) -> dict:
    per_query = []
    for item in golden_set:
        relevant_ids = set(item["relevant_chunk_ids"])
        query = item["query"]

        if mode == "dense_only":
            results = await pipeline.retriever._dense_retrieval([query], k=20)
        elif mode == "sparse_only":
            results = await pipeline.retriever._sparse_retrieval(query, k=20)
        elif mode == "hybrid":
            results = await pipeline.retriever.retrieve(query, k=20)
        elif mode == "hybrid_reranked":
            rrf_results = await pipeline.retriever.retrieve(query, k=20)
            scorer = APIRerankerScorer(pipeline.llm_client)
            results = await rerank(query, rrf_results[:40], scorer, top_k=10)
        else:
            raise ValueError(mode)

        per_query.append({
            "hit@5": hit_rate_at_k(results, relevant_ids, 5),
            "hit@10": hit_rate_at_k(results, relevant_ids, 10),
            "rr@10": reciprocal_rank_at_k(results, relevant_ids, 10),
            "ndcg@10": ndcg_at_k(results, relevant_ids, 10),
        })

    return aggregate(per_query)


async def run_benchmark(golden_set: list[dict]) -> dict:
    import redis.asyncio as redis

    settings = get_settings()
    pool = await create_pool(settings)
    redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    llm_client = build_client(settings, redis_client)
    pipeline = RetrievalPipeline(pool, llm_client)

    try:
        results = {}
        for mode in ("dense_only", "sparse_only", "hybrid", "hybrid_reranked"):
            logger.info("running condition: %s", mode)
            results[mode] = await run_condition(pipeline, golden_set, mode)
    finally:
        await redis_client.aclose()
        await close_pool(pool)

    return results


def render_markdown(results: dict) -> str:
    lines = [
        "# Retrieval Benchmark Results",
        "",
        "| Condition | Hit Rate@5 | Hit Rate@10 | MRR@10 | NDCG@10 |",
        "|---|---|---|---|---|",
    ]
    for mode, scores in results.items():
        lines.append(
            f"| {mode} | {scores['hit_rate@5']:.3f} | {scores['hit_rate@10']:.3f} | "
            f"{scores['mrr@10']:.3f} | {scores['ndcg@10']:.3f} |"
        )

    dense_mrr = results["dense_only"]["mrr@10"]
    hybrid_reranked_mrr = results["hybrid_reranked"]["mrr@10"]
    improvement_pct = ((hybrid_reranked_mrr - dense_mrr) / dense_mrr * 100) if dense_mrr > 0 else float("inf")
    passed = improvement_pct >= REQUIRED_MRR_IMPROVEMENT_PCT

    lines += [
        "",
        f"Hybrid+Reranked vs Dense-only MRR@10 improvement: **{improvement_pct:.1f}%** "
        f"(required: >= {REQUIRED_MRR_IMPROVEMENT_PCT}%) — {'PASSED' if passed else 'FAILED'}",
    ]
    return "\n".join(lines)


def main() -> None:
    golden_set = json.loads(GOLDEN_SET_PATH.read_text())
    if any(item.get("relevant_chunk_ids") == ["REPLACE_WITH_REAL_CHUNK_ID"] for item in golden_set):
        logger.error(
            "golden_set.json at %s still has placeholder chunk IDs — replace with real "
            "chunk IDs from your ingested corpus (the task calls for 50 questions) before running.",
            GOLDEN_SET_PATH,
        )
        sys.exit(1)

    results = asyncio.run(run_benchmark(golden_set))
    markdown = render_markdown(results)
    RESULTS_PATH.write_text(markdown)
    print(markdown)


if __name__ == "__main__":
    main()
