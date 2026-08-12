"""
Retrieval quality evaluation harness — run this against your real,
ingested corpus with live provider credentials before trusting the
pipeline. It is NOT runnable in an environment with no Postgres instance
and no LLM API keys (there is nothing to retrieve against).

Usage:
    python -m evaluation.retrieval_eval [--test-set evaluation/test_set.json]

Requires:
  - infra/docker-compose.yml stack up (Postgres with real ingested chunks)
  - OPENAI_API_KEY and/or ANTHROPIC_API_KEY set (embeddings + reranking)
  - evaluation/test_set.json filled in with real queries and real
    relevant_chunk_ids from YOUR corpus — the committed test_set.json is a
    template with placeholder entries, not real data (see its header
    comment). Replace it before trusting any number this script prints.

Writes evaluation/retrieval_results.json with both the RRF-only baseline
and the reranked scores (task requirement: "measure both").
"""
import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

from backend.config import get_settings
from backend.db.pool import close_pool, create_pool
from backend.providers.client import build_client
from evaluation.metrics import aggregate, hit_rate, reciprocal_rank
from pipelines.retrieval.pipeline import RetrievalPipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("neuroflow.evaluation.retrieval")

HIT_RATE_THRESHOLD = 0.75
MRR_THRESHOLD = 0.55

RESULTS_PATH = Path(__file__).parent / "retrieval_results.json"


async def _run_one(pipeline: RetrievalPipeline, query: str, relevant_ids: set[str], k: int):
    result = await pipeline.retrieve(query, k=k, final_k=k)
    rrf_top_k = result.rrf_chunks[:k]
    reranked_top_k = result.reranked_chunks[:k]

    return {
        "rrf_hit": hit_rate(rrf_top_k, relevant_ids),
        "rrf_rr": reciprocal_rank(rrf_top_k, relevant_ids),
        "reranked_hit": hit_rate(reranked_top_k, relevant_ids),
        "reranked_rr": reciprocal_rank(reranked_top_k, relevant_ids),
    }


async def run_evaluation(test_set: list[dict], k: int = 10) -> dict:
    settings = get_settings()
    pool = await create_pool(settings)

    import redis.asyncio as redis
    redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    llm_client = build_client(settings, redis_client)
    pipeline = RetrievalPipeline(pool, llm_client)

    rrf_hits, rrf_rrs = [], []
    reranked_hits, reranked_rrs = [], []
    per_query_detail = []

    started = time.perf_counter()
    try:
        for test in test_set:
            relevant_ids = set(test["relevant_chunk_ids"])
            outcome = await _run_one(pipeline, test["query"], relevant_ids, k)

            rrf_hits.append(outcome["rrf_hit"])
            rrf_rrs.append(outcome["rrf_rr"])
            reranked_hits.append(outcome["reranked_hit"])
            reranked_rrs.append(outcome["reranked_rr"])
            per_query_detail.append({"query": test["query"], **outcome})

            logger.info(
                "query=%r rrf_hit=%s rrf_rr=%.3f reranked_hit=%s reranked_rr=%.3f",
                test["query"], outcome["rrf_hit"], outcome["rrf_rr"],
                outcome["reranked_hit"], outcome["reranked_rr"],
            )
    finally:
        await redis_client.aclose()
        await close_pool(pool)

    duration_s = time.perf_counter() - started

    return {
        "k": k,
        "n_queries": len(test_set),
        "duration_s": round(duration_s, 1),
        "rrf_only": aggregate(rrf_hits, rrf_rrs),
        "reranked": aggregate(reranked_hits, reranked_rrs),
        "per_query": per_query_detail,
        "thresholds": {"hit_rate": HIT_RATE_THRESHOLD, "mrr": MRR_THRESHOLD},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-set", default=str(Path(__file__).parent / "test_set.json"))
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()

    test_set = json.loads(Path(args.test_set).read_text())
    if any(t.get("relevant_chunk_ids") in (None, [], ["REPLACE_WITH_REAL_CHUNK_ID"]) for t in test_set):
        logger.error(
            "test set at %s still contains placeholder chunk IDs — replace with real "
            "chunk IDs from your ingested corpus before running this evaluation.",
            args.test_set,
        )
        sys.exit(1)

    results = asyncio.run(run_evaluation(test_set, k=args.k))
    RESULTS_PATH.write_text(json.dumps(results, indent=2))

    reranked = results["reranked"]
    passed = reranked["hit_rate"] > HIT_RATE_THRESHOLD and reranked["mrr"] > MRR_THRESHOLD
    logger.info(
        "RRF-only: hit_rate=%.3f mrr=%.3f | Reranked: hit_rate=%.3f mrr=%.3f | thresholds: hit_rate>%.2f mrr>%.2f | %s",
        results["rrf_only"]["hit_rate"], results["rrf_only"]["mrr"],
        reranked["hit_rate"], reranked["mrr"],
        HIT_RATE_THRESHOLD, MRR_THRESHOLD,
        "PASSED" if passed else "FAILED",
    )
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
