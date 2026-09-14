import asyncio
import json
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from backend.config import settings
from backend.db.pool import get_pool
from backend.monitoring.metrics import queries_total
from backend.providers.client import NeuroFlowClient
from backend.resilience.rate_limiter import consume_pipeline_token, rate_limit_endpoint
from backend.security.auth import RequireScope
from backend.security.prompt_injection import (
    classify_prompt_injection,
    sanitize_text,
    scan_for_prompt_injection,
)
from pipelines.generation.generator import StreamingGenerator
from pipelines.retrieval.pipeline import RetrievalPipeline

router = APIRouter(prefix="/query", tags=["query"])


class QueryRequest(BaseModel):
    query: str = Field(..., max_length=5000)
    pipeline_id: UUID
    stream: bool = False


async def get_redis() -> Any:  # noqa: ANN401
    return aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
    )


@router.post("", dependencies=[Depends(rate_limit_endpoint(max_requests=60, window_seconds=60))])
async def submit_query(
    req: QueryRequest,
    request: Request,
    user: Any = Depends(RequireScope("query")),  # noqa: ANN401
) -> Any:  # noqa: ANN401
    pool = get_pool()
    req.query = sanitize_text(req.query)

    redis_client = await get_redis()
    client = NeuroFlowClient(redis_client)

    # Layer 1 Prompt Injection
    injection_metadata = {}
    l1_result = scan_for_prompt_injection(req.query)
    if l1_result:
        import logging

        logging.warning(f"Prompt injection pattern detected: {l1_result['pattern']}")
        injection_metadata = l1_result

    # Layer 2 Prompt Injection (LLM Classification)
    is_injection = await classify_prompt_injection(req.query, client)
    if is_injection:
        await redis_client.aclose()
        return JSONResponse(
            status_code=400,
            content={"error": "query_rejected", "reason": "potential_prompt_injection"},
        )

    # Create the run in DB
    async with pool.acquire() as conn:
        run_id = await conn.fetchval(
            """
            INSERT INTO pipeline_runs (pipeline_id, query, status, metadata)
            VALUES ($1, $2, 'pending', $3::jsonb)
            RETURNING id
            """,
            req.pipeline_id,
            req.query,
            json.dumps(injection_metadata),
        )

    if req.stream:
        return {"run_id": str(run_id)}

    # If not streaming, do it synchronously
    retrieval_pipeline = RetrievalPipeline(pool, client)
    generator = StreamingGenerator(client, pool, redis_client)

    # Fetch pipeline config
    pipeline_config = None
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT config FROM pipelines WHERE id = $1", req.pipeline_id)
        if row:
            pipeline_config = (
                json.loads(row["config"]) if isinstance(row["config"], str) else row["config"]
            )

    # Apply pipeline rate limit
    rpm = pipeline_config.get("rate_limit_rpm", 60) if pipeline_config else 60
    await consume_pipeline_token(str(req.pipeline_id), rpm)

    # Retrieval
    context_data = await retrieval_pipeline.get_context(
        req.query,
        config=pipeline_config,
        pipeline_id=str(req.pipeline_id),
        run_id=str(run_id),
    )

    # Generation
    full_text = ""
    citations = []

    # We must iterate the async generator
    stream_gen = generator.generate_stream(
        str(run_id),
        str(req.pipeline_id),
        req.query,
        context_data.get("query_type", "factual"),
        context_data,
        config=pipeline_config,
    )

    async for chunk, batch_citations in stream_gen:
        full_text += chunk
        if batch_citations:
            citations = batch_citations

    await redis_client.aclose()

    queries_total.labels(pipeline_id=str(req.pipeline_id), status="success").inc()

    return {
        "run_id": str(run_id),
        "answer": full_text,
        "citations": citations,
        "context_sources": [
            {"document_name": s.metadata.get("filename", "unknown"), "chunk_id": str(s.chunk_id)}
            for s in context_data["raw_results"]
        ],
    }


@router.get(
    "/{run_id}/stream",
    dependencies=[Depends(rate_limit_endpoint(max_requests=60, window_seconds=60))],
)
async def stream_query(
    run_id: UUID,
    request: Request,
    user: Any = Depends(RequireScope("query")),  # noqa: ANN401
) -> Any:  # noqa: ANN401
    pool = get_pool()

    # Verify run exists and is pending
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT query, pipeline_id FROM pipeline_runs WHERE id = $1", run_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Run not found")

    query = row["query"]
    pipeline_id = row["pipeline_id"]

    redis_client = await get_redis()
    client = NeuroFlowClient(redis_client)

    retrieval_pipeline = RetrievalPipeline(pool, client)
    generator = StreamingGenerator(client, pool, redis_client)

    async def event_generator() -> Any:  # noqa: ANN401
        try:
            # Keepalive task
            async def keepalive() -> Any:  # noqa: ANN401
                try:
                    while True:
                        await asyncio.sleep(15)
                        yield {"event": "keepalive", "data": json.dumps({"type": "keepalive"})}
                except asyncio.CancelledError:
                    pass

            # Retrieval Start
            yield {"event": "message", "data": json.dumps({"type": "retrieval_start"})}

            # Since retrieval can take time, we should run it in a way that allows keepalive to interleave?  # noqa: E501
            # sse-starlette natively doesn't interleave easily unless we use asyncio.wait with timeout,  # noqa: E501
            # but we can just use a simple background task if needed, or rely on fast retrieval.
            # To strictly follow "keepalive event every 15s if generation takes long", we can use a queue.  # noqa: E501

            queue = asyncio.Queue()  # type: ignore

            async def worker() -> Any:  # noqa: ANN401
                try:
                    pipeline_config = None
                    async with pool.acquire() as conn:
                        row = await conn.fetchrow(
                            "SELECT config FROM pipelines WHERE id = $1", pipeline_id
                        )
                        if row:
                            pipeline_config = (
                                json.loads(row["config"])
                                if isinstance(row["config"], str)
                                else row["config"]
                            )

                    rpm = pipeline_config.get("rate_limit_rpm", 60) if pipeline_config else 60
                    await consume_pipeline_token(str(pipeline_id), rpm)

                    context_data = await retrieval_pipeline.get_context(
                        query,
                        config=pipeline_config,
                        pipeline_id=str(pipeline_id),
                        run_id=str(run_id),
                    )
                    sources = [
                        s.metadata.get("filename", f"doc_{s.document_id}")
                        for s in context_data["raw_results"]
                    ]

                    await queue.put(
                        {
                            "type": "retrieval_complete",
                            "chunk_count": len(sources),
                            "sources": list(set(sources)),
                        }
                    )

                    stream_gen = generator.generate_stream(
                        str(run_id),
                        str(pipeline_id),
                        query,
                        context_data.get("query_type", "factual"),
                        context_data,
                        config=pipeline_config,
                    )
                    async for chunk, batch_citations in stream_gen:
                        if chunk:
                            await queue.put({"type": "token", "delta": chunk})
                        if batch_citations:
                            await queue.put(
                                {
                                    "type": "done",
                                    "run_id": str(run_id),
                                    "citations": batch_citations,
                                }
                            )
                            break

                    if not batch_citations:
                        await queue.put({"type": "done", "run_id": str(run_id), "citations": []})

                    queries_total.labels(pipeline_id=str(pipeline_id), status="success").inc()
                except Exception as e:
                    queries_total.labels(pipeline_id=str(pipeline_id), status="error").inc()
                    await queue.put({"type": "error", "message": str(e)})

            worker_task = asyncio.create_task(worker())

            while not worker_task.done() or not queue.empty():
                try:
                    # Wait for item with 15s timeout
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {"event": "message", "data": json.dumps(msg)}

                    if msg.get("type") in ["done", "error"]:
                        break
                except TimeoutError:
                    yield {"event": "message", "data": json.dumps({"type": "keepalive"})}

        finally:
            await redis_client.aclose()

    return EventSourceResponse(event_generator())
