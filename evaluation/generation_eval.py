import asyncio
import json
import logging
from typing import Any

from redis.asyncio import Redis

from backend.config import settings
from backend.db.pool import close_pool, create_pool, get_pool
from backend.providers.base import ChatMessage
from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria
from evaluation.metrics.answer_relevance import evaluate_answer_relevance
from evaluation.metrics.context_precision import evaluate_context_precision
from evaluation.metrics.faithfulness import evaluate_faithfulness
from pipelines.generation.prompt_builder import build_prompt
from pipelines.retrieval.pipeline import RetrievalPipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_variant_eval(pipeline: RetrievalPipeline, test_set: list[dict[str, Any]], variant: str, redis_client: Redis) -> dict[str, Any]:  # noqa: E501
    """Run a real A/B evaluation of a prompt variant: retrieve context, generate a
    real answer from the LLM, then score it with the genuine LLM-as-judge metrics
    (evaluation/metrics/*). This previously used mock random.uniform() scores that
    were hardcoded to make variant B win regardless of what was generated -- that
    has been removed. Scores now depend entirely on what the model actually produces.
    """
    import mlflow

    mlflow.set_tracking_uri(
        settings.mlflow_uri if hasattr(settings, "mlflow_uri") else "http://localhost:5000"
    )
    mlflow.set_experiment("Prompt_AB_Testing")

    logger.info(f"Evaluating generation quality for Variant {variant}...")

    client = pipeline.client if hasattr(pipeline, "client") else NeuroFlowClient(redis_client)
    criteria = RoutingCriteria(task_type="evaluation")

    faithfulness_scores = []
    relevance_scores = []
    precision_scores = []
    overall_scores = []

    with mlflow.start_run(run_name=f"Prompt_Variant_{variant}"):
        mlflow.log_param("prompt_variant", variant)

        for i, test in enumerate(test_set):
            query = test["query"]
            try:
                # Pass the prompt variant via config
                config = {"generation": {"prompt_variant": variant}}
                context_result = await pipeline.get_context(query, config=config)

                assembled_context = context_result["context_data"]
                query_type = context_result.get("query_type", "factual")
                chunks = [r.content for r in context_result.get("raw_results", [])]

                prompt = build_prompt(query, assembled_context, query_type)
                gen_result = await client.chat(
                    [ChatMessage(role="user", content=prompt)], criteria
                )
                answer = gen_result.content

                f_score, r_score, p_score = await asyncio.gather(
                    evaluate_faithfulness(query, answer, assembled_context, client),
                    evaluate_answer_relevance(query, answer, client),
                    evaluate_context_precision(query, chunks, answer, client),
                )

                o_score = (f_score + r_score + p_score) / 3

                faithfulness_scores.append(f_score)
                relevance_scores.append(r_score)
                precision_scores.append(p_score)
                overall_scores.append(o_score)
            except Exception as e:
                logger.error(f"Error evaluating query: {e}")

        avg_f = sum(faithfulness_scores) / len(faithfulness_scores) if faithfulness_scores else 0
        avg_r = sum(relevance_scores) / len(relevance_scores) if relevance_scores else 0
        avg_p = sum(precision_scores) / len(precision_scores) if precision_scores else 0
        avg_o = sum(overall_scores) / len(overall_scores) if overall_scores else 0

        mlflow.log_metric("faithfulness", avg_f)
        mlflow.log_metric("answer_relevance", avg_r)
        mlflow.log_metric("context_precision", avg_p)
        mlflow.log_metric("overall_score", avg_o)

        logger.info(f"--- Variant {variant} Results ---")
        logger.info(f"Faithfulness: {avg_f:.4f} (Target > 0.78)")
        logger.info(f"Answer Relevance: {avg_r:.4f} (Target > 0.75)")
        logger.info(f"Context Precision: {avg_p:.4f} (Target > 0.72)")
        logger.info(f"Overall Score: {avg_o:.4f} (Target > 0.75)")

        return {
            "faithfulness": avg_f,
            "answer_relevance": avg_r,
            "context_precision": avg_p,
            "overall_score": avg_o,
            "num_samples": len(test_set),
        }


async def run_generation_eval() -> None:
    redis_client = Redis(
        host=settings.redis_host, port=settings.redis_port, password=settings.redis_password
    )
    client = NeuroFlowClient(redis_client)

    await create_pool()
    pool = get_pool()

    pipeline = RetrievalPipeline(pool, client)

    # 1. Generate 30 questions
    logger.info("Generating 30-question test set...")
    test_set = []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, content FROM chunks WHERE length(content) > 100 ORDER BY RANDOM() LIMIT 30"
        )

    if not rows:
        logger.warning("No chunks found. Creating synthetic queries.")
        test_set = [{"query": f"Test question {i}", "expected": "answer"} for i in range(30)]
    else:
        criteria = RoutingCriteria(task_type="evaluation")
        for row in rows:
            content = row["content"]
            prompt = (
                f"Given this text, generate a single clear question. Text: {content}\n\nQuestion:"
            )
            try:
                res = await client.chat([ChatMessage(role="user", content=prompt)], criteria)
                test_set.append({"query": res.content.strip()})
            except Exception as e:
                logger.error(f"Failed to generate query: {e}")

    # 2. Run A/B Test
    res_a = await run_variant_eval(pipeline, test_set, "A", redis_client)
    res_b = await run_variant_eval(pipeline, test_set, "B", redis_client)

    with open("evaluation/generation_results.json", "w") as f:  # noqa: ASYNC230
        json.dump({"Variant_A": res_a, "Variant_B": res_b}, f, indent=2)

    await close_pool()
    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(run_generation_eval())
