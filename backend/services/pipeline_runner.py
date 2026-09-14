"""
Shared orchestration: load a pipeline's config, run retrieval and
generation with THAT config actually applied (dense_k/sparse_k/
top_k_after_rerank/reranker/query_expansion/temperature/max_cost_per_call/
system_prompt_variant), and return a normalized result. Used by both
backend/api/query.py (single-pipeline queries, optionally streamed) and
backend/api/compare.py (A/B, both pipelines run through this same
function via asyncio.gather) — so "the config actually changes behavior"
is implemented exactly once.
"""
import json
import logging
import time
from typing import Awaitable, Callable

import asyncpg

from backend.models.pipeline import PipelineConfig
from backend.providers.client import NeuroFlowClient
from backend.resilience.rate_limiter import RateLimitExceeded, acquire_pipeline_tokens
from pipelines.generation.generator import create_pipeline_run, generate, mark_run_failed
from pipelines.retrieval.pipeline import RetrievalPipeline

logger = logging.getLogger("neuroflow.services.pipeline_runner")

from opentelemetry import trace
tracer = trace.get_tracer("neuroflow.services")

EmitFn = Callable[[dict], Awaitable[None]]


class PipelineNotFound(Exception):
    pass


async def load_pipeline_config(pool: asyncpg.Pool, pipeline_id: str) -> PipelineConfig:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT name, description, config FROM pipelines WHERE id = $1 AND status != 'archived'",
            pipeline_id,
        )
    if row is None:
        raise PipelineNotFound(f"pipeline {pipeline_id} not found or archived")

    config_dict = row["config"]
    if isinstance(config_dict, str):
        config_dict = json.loads(config_dict)

    return PipelineConfig(name=row["name"], description=row["description"], **config_dict)


async def run_pipeline_for_query(
    *,
    pool: asyncpg.Pool,
    llm_client: NeuroFlowClient,
    arq_pool,
    pipeline_id: str,
    query: str,
    emit_event: EmitFn | None = None,
    run_id: str | None = None,
) -> dict:
    """`emit_event`, if given, is awaited with every SSE-shaped event as
    the pipeline runs (query.py uses this to publish to Redis for
    streaming); if None, events aren't published anywhere, only the final
    return value is used (compare.py's case — no client is tailing an SSE
    stream for an A/B comparison call).

    `run_id`: pass a pre-created pipeline_runs id (from
    generator.create_pipeline_run) when the caller needs to know the
    run_id BEFORE this function returns — e.g. POST /query's streaming
    path returns run_id to the client immediately, before retrieval even
    starts, so it must exist first. If omitted, a run is created here.

    NOTE on eval_score: evaluation is enqueued fire-and-forget (Task 37's
    architecture: generation must not block on evaluation), so it is
    NEVER available synchronously in this function's return value —
    callers that want it (e.g. the A/B compare response) must poll
    GET /pipelines/{id}/runs or GET /runs/{run_id} afterward.
    """
    async def _emit(event: dict) -> None:
        if emit_event is not None:
            await emit_event(event)

    config = await load_pipeline_config(pool, pipeline_id)

    if config.rate_limit_rpm is not None:
        try:
            await acquire_pipeline_tokens(llm_client.redis, pipeline_id, config.rate_limit_rpm)
        except RateLimitExceeded as e:
            logger.warning("pipeline_id=%s rate limit exceeded: %s", pipeline_id, e)
            await _emit({"type": "error", "message": "pipeline rate limit exceeded", "retry_after": e.retry_after})
            return {"error": "pipeline rate limit exceeded", "retry_after": e.retry_after}

    if run_id is None:
        run_id = await create_pipeline_run(pool, pipeline_id, query)

    await _emit({"type": "retrieval_start"})

    retrieval_pipeline = RetrievalPipeline(pool, llm_client)
    total_started = time.perf_counter()
    retrieval_started = time.perf_counter()

    try:
        result = await retrieval_pipeline.retrieve(
            query,
            dense_k=config.retrieval.dense_k,
            sparse_k=config.retrieval.sparse_k,
            rerank_candidates=max(config.retrieval.dense_k, config.retrieval.sparse_k),
            final_k=config.retrieval.top_k_after_rerank,
            token_budget=config.generation.max_context_tokens,
            enable_query_expansion=config.retrieval.query_expansion,
            reranker=config.retrieval.reranker,
        )
    except Exception:
        logger.exception("retrieval failed for run_id=%s", run_id)
        await mark_run_failed(pool, run_id, error="retrieval failed", pipeline_id=pipeline_id)
        await _emit({"type": "error", "message": "retrieval failed"})
        return {"run_id": run_id, "error": "retrieval failed"}

    retrieval_latency_ms = round((time.perf_counter() - retrieval_started) * 1000)

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE pipeline_runs SET retrieval_latency_ms = $2 WHERE id = $1", run_id, retrieval_latency_ms
        )

    source_docs = sorted({s["document_name"] for s in result.assembled.sources if s.get("document_name")})
    await _emit({
        "type": "retrieval_complete",
        "chunk_count": len(result.assembled.chunks_used),
        "sources": source_docs,
    })

    generation_parts: list[str] = []
    citations: list[dict] = []
    try:
        with tracer.start_as_current_span("generation.pipeline") as gen_span:
            gen_span.set_attribute("run_id", run_id)
            gen_span.set_attribute("pipeline_id", pipeline_id)
            async for event in generate(
                pool=pool, llm_client=llm_client, arq_pool=arq_pool,
                run_id=run_id, pipeline_id=pipeline_id, query=query,
                query_type=result.processed_query.query_type,
                assembled=result.assembled,
                temperature=config.generation.temperature,
                max_cost_per_call=config.generation.model_routing.max_cost_per_call,
                prompt_variant=config.generation.system_prompt_variant,
            ):
                await _emit(event)
                if event["type"] == "token":
                    generation_parts.append(event["delta"])
                elif event["type"] == "done":
                    citations = event["citations"]
    except Exception:
        logger.exception("generation failed for run_id=%s", run_id)
        await mark_run_failed(pool, run_id, error="generation failed", pipeline_id=pipeline_id)
        await _emit({"type": "error", "message": "generation failed"})
        return {
            "run_id": run_id,
            "error": "generation failed",
            "retrieval_latency_ms": retrieval_latency_ms,
        }

    total_latency_ms = round((time.perf_counter() - total_started) * 1000)

    return {
        "run_id": run_id,
        "generation": "".join(generation_parts),
        "citations": citations,
        "sources": source_docs,
        "chunks_used": len(result.assembled.chunks_used),
        "retrieval_latency_ms": retrieval_latency_ms,
        "total_latency_ms": total_latency_ms,
    }
