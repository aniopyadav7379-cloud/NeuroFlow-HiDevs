import asyncio
import json
import logging
from typing import Any

import asyncpg

from backend.db.pool import close_pool, create_pool, get_pool
from backend.providers.base import ChatMessage
from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria
from pipelines.retrieval.pipeline import RetrievalPipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def generate_synthetic_test_set(
    pool: asyncpg.Pool,
    client: NeuroFlowClient,
    num_samples: int = 20,  # noqa: ANN401
) -> list[dict[str, Any]]:
    test_set = []

    async with pool.acquire() as conn:
        # Get random chunks that are large enough to have meaningful content
        rows = await conn.fetch(
            """
            SELECT id, content 
            FROM chunks 
            WHERE length(content) > 50 
            ORDER BY RANDOM() 
            LIMIT $1
        """,
            num_samples,
        )

    if not rows:
        raise ValueError("No chunks found in the database. Please run ingestion first.")

    criteria = RoutingCriteria(task_type="evaluation")

    for row in rows:
        chunk_id = str(row["id"])
        content = row["content"]

        prompt = f"Given this text, generate a single clear, specific question that this text perfectly answers. Text: {content}\n\nQuestion:"  # noqa: E501

        try:
            result = await client.chat([ChatMessage(role="user", content=prompt)], criteria)
            question = result.content.strip()

            test_set.append({"query": question, "relevant_chunk_ids": [chunk_id]})
            logger.info(f"Generated query for chunk {chunk_id}: {question}")
        except Exception as e:
            logger.error(f"Failed to generate question for {chunk_id}: {e}")

    return test_set


async def run_evaluation() -> None:
    from redis.asyncio import Redis

    from backend.config import settings

    redis_client = Redis(
        host=settings.redis_host, port=settings.redis_port, password=settings.redis_password
    )
    client = NeuroFlowClient(redis_client)

    await create_pool()
    pool = get_pool()

    pipeline = RetrievalPipeline(pool, client)

    # 1. Generate or load test set
    logger.info("Generating synthetic test set from database chunks...")
    try:
        test_set = await generate_synthetic_test_set(pool, client, num_samples=20)
    except Exception as e:
        logger.error(str(e))
        await close_pool()
        return

    if not test_set:
        logger.error("Failed to generate test set.")
        await close_pool()
        return

    # 2. Run evaluation
    logger.info("Running evaluation...")
    hits = 0
    mrr_sum = 0.0

    for i, test in enumerate(test_set):
        query = test["query"]
        relevant_ids = test["relevant_chunk_ids"]

        results = await pipeline.retrieve(query, k=10)

        hit = any(r.chunk_id in relevant_ids for r in results)
        if hit:
            hits += 1

        rank = next((i + 1 for i, r in enumerate(results) if r.chunk_id in relevant_ids), None)
        if rank is not None:
            mrr_sum += 1.0 / rank

        logger.info(f"[{i + 1}/{len(test_set)}] Query: '{query}' | Hit: {hit} | Rank: {rank}")

    hit_rate = hits / len(test_set)
    mrr = mrr_sum / len(test_set)

    logger.info("--- Final Results ---")
    logger.info(f"Hit Rate: {hit_rate:.4f} (Target > 0.75)")
    logger.info(f"MRR: {mrr:.4f} (Target > 0.55)")

    # 3. Save results
    results_data = {"hit_rate": hit_rate, "mrr": mrr, "num_samples": len(test_set)}

    with open("evaluation/retrieval_results.json", "w") as f:  # noqa: ASYNC230
        json.dump(results_data, f, indent=2)

    await close_pool()
    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(run_evaluation())
