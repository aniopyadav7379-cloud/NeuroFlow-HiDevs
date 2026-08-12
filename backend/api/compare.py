"""
POST /pipelines/compare — runs the same query through two pipelines
simultaneously (asyncio.gather) and returns results side by side.
Evaluation for both runs is enqueued automatically as a side effect of
pipelines/generation/generator.generate()'s step 6 — nothing extra needed
here to satisfy "enqueue evaluation jobs for both runs".
"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.services.pipeline_runner import PipelineNotFound, load_pipeline_config, run_pipeline_for_query

logger = logging.getLogger("neuroflow.api.compare")
router = APIRouter()


class CompareRequest(BaseModel):
    query: str
    pipeline_a_id: str
    pipeline_b_id: str


class PipelineCompareResult(BaseModel):
    run_id: str | None = None
    generation: str | None = None
    retrieval_latency_ms: int | None = None
    total_latency_ms: int | None = None
    chunks_used: int | None = None
    eval_score: float | None = None  # always None here — see module note below
    error: str | None = None


class CompareResponse(BaseModel):
    query: str
    pipeline_a: PipelineCompareResult
    pipeline_b: PipelineCompareResult


def _to_compare_result(raw: dict) -> PipelineCompareResult:
    return PipelineCompareResult(
        run_id=raw.get("run_id"),
        generation=raw.get("generation"),
        retrieval_latency_ms=raw.get("retrieval_latency_ms"),
        total_latency_ms=raw.get("total_latency_ms"),
        chunks_used=raw.get("chunks_used"),
        # eval_score is intentionally always None in this response: the
        # task's example response includes it, but evaluation is enqueued
        # fire-and-forget (Task 37) and genuinely isn't ready by the time
        # this endpoint returns. Faking a synchronous value here would
        # mean either blocking this endpoint on an LLM judge call (which
        # contradicts the fire-and-forget architecture Task 37
        # deliberately built) or returning a number that isn't real yet.
        # Poll GET /pipelines/{id}/runs or GET /runs/{run_id} once the
        # evaluation job (enqueued as part of this call) completes.
        eval_score=None,
        error=raw.get("error"),
    )


@router.post("/pipelines/compare", response_model=CompareResponse)
async def compare_pipelines(request: Request, body: CompareRequest) -> CompareResponse:
    pool = request.app.state.pg_pool
    llm_client = request.app.state.llm_client
    arq_pool = request.app.state.arq_pool

    for pid in (body.pipeline_a_id, body.pipeline_b_id):
        try:
            await load_pipeline_config(pool, pid)
        except PipelineNotFound:
            raise HTTPException(status_code=404, detail=f"pipeline {pid} not found or archived")

    result_a, result_b = await asyncio.gather(
        run_pipeline_for_query(pool=pool, llm_client=llm_client, arq_pool=arq_pool, pipeline_id=body.pipeline_a_id, query=body.query),
        run_pipeline_for_query(pool=pool, llm_client=llm_client, arq_pool=arq_pool, pipeline_id=body.pipeline_b_id, query=body.query),
    )

    return CompareResponse(
        query=body.query,
        pipeline_a=_to_compare_result(result_a),
        pipeline_b=_to_compare_result(result_b),
    )
