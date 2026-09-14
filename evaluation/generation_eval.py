"""
Task 18 generation evaluation.

This script executes REAL end-to-end pipeline runs (retrieval -> generation)
and scores them with the repository's existing LLM-as-judge implementation
(``evaluation.judge.EvaluationJudge``, backed by ``evaluation/metrics/*.py``).

It intentionally does NOT invent, mock, or randomly sample scores. If any
required piece of infrastructure (Postgres, Redis, chunks, LLM provider) is
unavailable, the script fails loudly and writes a result file with
``"status": "unavailable"`` plus the reason instead of a passing-looking
number.

Reused (not re-implemented) from the existing codebase:
- evaluation.retrieval_eval.generate_synthetic_test_set  -> test query generation
- evaluation.judge.EvaluationJudge                        -> faithfulness /
  answer_relevance / context_precision / context_recall / overall_score,
  via evaluation/metrics/*.py
- pipelines.retrieval.pipeline.RetrievalPipeline           -> retrieval
- pipelines.generation.generator.StreamingGenerator        -> generation
- backend.db.pool / backend.config.settings                -> infra config
"""

import asyncio
import json
import logging
import uuid
from typing import Any

import asyncpg
from redis.asyncio import Redis

from backend.config import settings
from backend.db.pool import close_pool, create_pool, get_pool
from backend.providers.client import NeuroFlowClient
from evaluation.judge import EvaluationJudge
from evaluation.retrieval_eval import generate_synthetic_test_set
from pipelines.generation.generator import StreamingGenerator
from pipelines.retrieval.pipeline import RetrievalPipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RESULTS_PATH = "evaluation/generation_results.json"

TARGETS = {
    "faithfulness": 0.78,
    "answer_relevance": 0.75,
    "context_precision": 0.72,
    "overall_score": 0.75,
}


def _write_unavailable(reason: str, detail: str = "") -> None:
    """Persist an explicit 'evaluation could not run' result. Never a fake score."""
    payload = {
        "status": "unavailable",
        "reason": reason,
        "detail": detail,
        "faithfulness": None,
        "answer_relevance": None,
        "context_precision": None,
        "overall_score": None,
        "num_samples": 0,
    }
    with open(RESULTS_PATH, "w") as f:
        json.dump(payload, f, indent=2)
    logger.error(f"Generation evaluation UNAVAILABLE: {reason} - {detail}")


async def _get_or_create_eval_pipeline(pool: asyncpg.Pool) -> str:
    """
    Reuse an existing pipeline row (same pattern as infra/seed.sql:
    `SELECT id INTO p_id FROM pipelines LIMIT 1`). Only create one if the
    project genuinely has none yet - this is a normal DB row insert against
    the existing schema, not a parallel/mock architecture.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM pipelines LIMIT 1")
        if row:
            return str(row["id"])

        row = await conn.fetchrow(
            """
            INSERT INTO pipelines (name, config)
            VALUES ($1, $2::jsonb)
            RETURNING id
            """,
            f"task18-generation-eval-{uuid.uuid4().hex[:8]}",
            json.dumps({"retrieval": {}, "generation": {}}),
        )
        return str(row["id"])


async def _run_one(
    pool: asyncpg.Pool,
    retrieval_pipeline: RetrievalPipeline,
    generator: StreamingGenerator,
    judge: EvaluationJudge,
    pipeline_id: str,
    query: str,
    variant: str,
) -> dict[str, Any]:
    """Run one real retrieval+generation+judge pass for a single query."""
    config = {"generation": {"prompt_variant": variant}}

    async with pool.acquire() as conn:
        run_id = await conn.fetchval(
            """
            INSERT INTO pipeline_runs (pipeline_id, query, status)
            VALUES ($1, $2, 'pending')
            RETURNING id
            """,
            uuid.UUID(pipeline_id),
            query,
        )
    run_id = str(run_id)

    context_data = await retrieval_pipeline.get_context(
        query, config=config, pipeline_id=pipeline_id, run_id=run_id
    )

    full_text = ""
    async for chunk, _citations in generator.generate_stream(
        run_id,
        pipeline_id,
        query,
        context_data.get("query_type", "factual"),
        context_data,
        config=config,
    ):
        full_text += chunk

    if not full_text.strip():
        raise RuntimeError(f"Empty generation for run {run_id}; nothing to judge.")

    # Real LLM-as-judge scoring via the existing evaluate_run path (writes to
    # the `evaluations` table exactly like a production run would).
    overall = await judge.evaluate_run(run_id)
    if overall is None:
        raise RuntimeError(f"EvaluationJudge could not evaluate run {run_id}.")

    async with pool.acquire() as conn:
        eval_row = await conn.fetchrow(
            """
            SELECT faithfulness, answer_relevance, context_precision, context_recall, overall_score
            FROM evaluations WHERE run_id = $1
            ORDER BY evaluated_at DESC LIMIT 1
            """,
            uuid.UUID(run_id),
        )

    if not eval_row:
        raise RuntimeError(f"No evaluations row found for run {run_id} after judging.")

    return {
        "run_id": run_id,
        "query": query,
        "faithfulness": eval_row["faithfulness"],
        "answer_relevance": eval_row["answer_relevance"],
        "context_precision": eval_row["context_precision"],
        "context_recall": eval_row["context_recall"],
        "overall_score": eval_row["overall_score"],
    }


async def run_variant_eval(
    pool: asyncpg.Pool,
    retrieval_pipeline: RetrievalPipeline,
    generator: StreamingGenerator,
    judge: EvaluationJudge,
    pipeline_id: str,
    test_set: list[dict[str, Any]],
    variant: str,
) -> dict[str, Any]:
    import mlflow

    mlflow.set_tracking_uri(getattr(settings, "mlflow_uri", "http://localhost:5000"))
    mlflow.set_experiment("Prompt_AB_Testing")

    logger.info(f"Evaluating generation quality for Variant {variant} ({len(test_set)} queries)...")

    per_sample: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    with mlflow.start_run(run_name=f"Prompt_Variant_{variant}"):
        mlflow.log_param("prompt_variant", variant)
        mlflow.log_param("num_queries", len(test_set))

        for i, test in enumerate(test_set):
            query = test["query"]
            try:
                result = await _run_one(
                    pool, retrieval_pipeline, generator, judge, pipeline_id, query, variant,
                )
                per_sample.append(result)
                logger.info(
                    f"[{variant}][{i + 1}/{len(test_set)}] overall={result['overall_score']:.3f}"
                )
            except Exception as e:
                logger.error(f"[{variant}] query {i + 1} failed: {e}")
                errors.append({"query": query, "error": str(e)})

        if not per_sample:
            mlflow.log_param("status", "all_samples_failed")
            return {
                "faithfulness": None,
                "answer_relevance": None,
                "context_precision": None,
                "overall_score": None,
                "num_samples": 0,
                "num_errors": len(errors),
                "errors": errors,
                "samples": [],
            }

        def _avg(key: str) -> float:
            vals = [s[key] for s in per_sample if s[key] is not None]
            return sum(vals) / len(vals) if vals else 0.0

        avg_f = _avg("faithfulness")
        avg_r = _avg("answer_relevance")
        avg_p = _avg("context_precision")
        avg_o = _avg("overall_score")

        mlflow.log_metric("faithfulness", avg_f)
        mlflow.log_metric("answer_relevance", avg_r)
        mlflow.log_metric("context_precision", avg_p)
        mlflow.log_metric("overall_score", avg_o)
        mlflow.log_metric("num_samples", len(per_sample))
        mlflow.log_metric("num_errors", len(errors))

        logger.info(f"--- Variant {variant} Results (n={len(per_sample)}) ---")
        logger.info(f"Faithfulness: {avg_f:.4f} (Target > {TARGETS['faithfulness']})")
        logger.info(f"Answer Relevance: {avg_r:.4f} (Target > {TARGETS['answer_relevance']})")
        logger.info(f"Context Precision: {avg_p:.4f} (Target > {TARGETS['context_precision']})")
        logger.info(f"Overall Score: {avg_o:.4f} (Target > {TARGETS['overall_score']})")

        return {
            "faithfulness": avg_f,
            "answer_relevance": avg_r,
            "context_precision": avg_p,
            "overall_score": avg_o,
            "num_samples": len(per_sample),
            "num_errors": len(errors),
            "errors": errors,
            "samples": per_sample,
        }


async def run_generation_eval() -> None:
    redis_client = Redis(
        host=settings.redis_host, port=settings.redis_port, password=settings.redis_password
    )
    try:
        await redis_client.ping()
    except Exception as e:
        _write_unavailable("redis_unreachable", str(e))
        return

    client = NeuroFlowClient(redis_client)

    try:
        await create_pool()
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception as e:
        _write_unavailable("postgres_unreachable", str(e))
        await redis_client.aclose()
        return

    try:
        pipeline_id = await _get_or_create_eval_pipeline(pool)
    except Exception as e:
        _write_unavailable("pipeline_row_unavailable", str(e))
        await close_pool()
        await redis_client.aclose()
        return

    retrieval_pipeline = RetrievalPipeline(pool, client)
    generator = StreamingGenerator(client, pool, redis_client)
    judge = EvaluationJudge(pool, redis_client)

    logger.info(
        "Generating test set from real ingested chunks (reusing retrieval_eval's generator)..."
    )
    try:
        test_set = await generate_synthetic_test_set(pool, client, num_samples=15)
    except ValueError as e:
        # No chunks ingested -> cannot evaluate generation quality honestly.
        _write_unavailable("no_ingested_chunks", str(e))
        await close_pool()
        await redis_client.aclose()
        return

    if not test_set:
        _write_unavailable("test_set_generation_failed", "LLM produced no usable queries.")
        await close_pool()
        await redis_client.aclose()
        return

    try:
        res_a = await run_variant_eval(
            pool, retrieval_pipeline, generator, judge, pipeline_id, test_set, "A",
        )
        res_b = await run_variant_eval(
            pool, retrieval_pipeline, generator, judge, pipeline_id, test_set, "B",
        )
    except Exception as e:
        _write_unavailable("evaluation_run_failed", str(e))
        await close_pool()
        await redis_client.aclose()
        return

    output = {
        "status": "ok" if (res_a["num_samples"] and res_b["num_samples"]) else "partial",
        "targets": TARGETS,
        "Variant_A": res_a,
        "Variant_B": res_b,
    }

    with open(RESULTS_PATH, "w") as f:
        json.dump(output, f, indent=2)

    logger.info(f"Wrote real evaluation results to {RESULTS_PATH}")

    await close_pool()
    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(run_generation_eval())
