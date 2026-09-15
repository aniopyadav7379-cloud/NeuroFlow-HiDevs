import asyncio
import json
import time
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.config import settings
from backend.db.pool import get_pool
from backend.providers.client import NeuroFlowClient
from evaluation.judge import EvaluationJudge
from pipelines.generation.generator import StreamingGenerator
from pipelines.retrieval.pipeline import RetrievalPipeline

router = APIRouter(prefix="/pipelines/compare", tags=["Admin"])

class CompareRequest(BaseModel):
    query: str = Field(
        ...,
        description="The test query to run across both pipelines concurrently.",
        examples=["What is the capital of France?"]
    )
    pipeline_a_id: UUID = Field(
        ...,
        description="The ID of the first pipeline (usually the baseline).",
        examples=["123e4567-e89b-12d3-a456-426614174000"]
    )
    pipeline_b_id: UUID = Field(
        ...,
        description="The ID of the second pipeline (usually the challenger).",
        examples=["987e6543-e21b-34d3-a456-426614174000"]
    )


async def get_redis() -> Any:  # noqa: ANN401
    return aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
    )


async def run_pipeline(
    pool: Any,  # noqa: ANN401
    redis_client: Any,  # noqa: ANN401
    pipeline_id: UUID,
    query: str,
) -> dict[str, Any]:
    # Fetch pipeline version and config to associate with run
    pipeline_config = None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT version, config FROM pipelines WHERE id = $1", pipeline_id
        )
        if not row:
            raise ValueError(f"Pipeline {pipeline_id} not found")
        pipeline_version = row["version"]
        pipeline_config = (
            json.loads(row["config"]) if isinstance(row["config"], str) else row["config"]
        )

        run_id = await conn.fetchval(
            """
            INSERT INTO pipeline_runs (pipeline_id, pipeline_version, query, status)
            VALUES ($1, $2, $3, 'pending')
            RETURNING id
            """,
            pipeline_id,
            pipeline_version,
            query,
        )

    start_time = time.time()

    client = NeuroFlowClient(redis_client)
    retrieval_pipeline = RetrievalPipeline(pool, client)
    generator = StreamingGenerator(client, pool, redis_client)

    try:
        # Retrieval
        retrieval_start = time.time()
        context_data = await retrieval_pipeline.get_context(query, config=pipeline_config)
        retrieval_latency_ms = int((time.time() - retrieval_start) * 1000)

        # Generation
        full_text = ""

        stream_gen = generator.generate_stream(
            str(run_id),
            str(pipeline_id),
            query,
            context_data.get("query_type", "factual"),
            context_data,
            config=pipeline_config,
        )
        async for chunk, batch_citations in stream_gen:
            full_text += chunk

        total_latency_ms = int((time.time() - start_time) * 1000)

        # Update retrieval latency
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE pipeline_runs SET retrieval_latency_ms = $1 WHERE id = $2",
                retrieval_latency_ms,
                run_id,
            )

        # Evaluation Job
        judge = EvaluationJudge(pool, redis_client)
        eval_score = await judge.evaluate_run(str(run_id))

        return {
            "run_id": str(run_id),
            "generation": full_text,
            "retrieval_latency_ms": retrieval_latency_ms,
            "total_latency_ms": total_latency_ms,
            "chunks_used": len(context_data.get("raw_results", [])),
            "eval_score": eval_score,
        }
    except Exception as e:
        async with pool.acquire() as conn:
            await conn.execute("UPDATE pipeline_runs SET status = 'failed' WHERE id = $1", run_id)
        raise e


@router.post(
    "",
    summary="A/B Test Pipelines",
    description=(
        "Executes a single RAG query against two different pipelines concurrently. "
        "Returns a side-by-side comparison of the generated answers, retrieval latency, "
        "total latency, chunks used, and automated evaluation scores. This is highly "
        "useful for comparing a baseline model against a challenger model. Requires 'admin' scope."
    ),
    response_description=(
        "A JSON object containing the query and the results for pipeline_a and pipeline_b."
    )
)
async def compare_pipelines(req: CompareRequest) -> Any:  # noqa: ANN401
    pool = get_pool()
    redis_client = await get_redis()

    try:
        task_a = run_pipeline(pool, redis_client, req.pipeline_a_id, req.query)
        task_b = run_pipeline(pool, redis_client, req.pipeline_b_id, req.query)

        res_a, res_b = await asyncio.gather(task_a, task_b, return_exceptions=True)

        response = {"query": req.query}

        if isinstance(res_a, Exception):  # type: ignore
            response["pipeline_a"] = {"error": str(res_a)}  # type: ignore
        else:
            response["pipeline_a"] = res_a  # type: ignore

        if isinstance(res_b, Exception):  # type: ignore
            response["pipeline_b"] = {"error": str(res_b)}  # type: ignore
        else:
            response["pipeline_b"] = res_b  # type: ignore

        return response
    finally:
        await redis_client.aclose()
