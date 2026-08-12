"""
POST /query and GET /query/{run_id}/stream — the generation-facing HTTP
surface. POST runs the whole pipeline synchronously (stream=false) or
pre-creates the run and kicks off a background task (stream=true),
returning run_id immediately; GET tails that background task's events
over SSE. All actual retrieval/generation logic — including applying a
pipeline's config (Task 38) — lives in backend/services/pipeline_runner.py,
shared with backend/api/compare.py.
"""
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from backend.resilience.rate_limit_dependency import rate_limit
from backend.services.pipeline_runner import PipelineNotFound, load_pipeline_config, run_pipeline_for_query
from pipelines.generation.events import consume_events, publish_event
from pipelines.generation.generator import create_pipeline_run

logger = logging.getLogger("neuroflow.api.query")
router = APIRouter()

QUERY_RATE_LIMIT = rate_limit(60, 60, key_prefix="query")  # 60 requests/minute per IP


class QueryRequest(BaseModel):
    query: str
    pipeline_id: str
    stream: bool = True


class QueryQueuedResponse(BaseModel):
    run_id: str
    status: str = "queued"


@router.post("/query", dependencies=[Depends(QUERY_RATE_LIMIT)])
async def query(request: Request, body: QueryRequest):
    pool = request.app.state.pg_pool
    llm_client = request.app.state.llm_client
    arq_pool = request.app.state.arq_pool
    redis_client = request.app.state.redis

    # Validate the pipeline exists before doing anything else, for both
    # paths — a 404 here should never depend on stream=true/false.
    try:
        await load_pipeline_config(pool, body.pipeline_id)
    except PipelineNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))

    if not body.stream:
        result = await run_pipeline_for_query(
            pool=pool, llm_client=llm_client, arq_pool=arq_pool,
            pipeline_id=body.pipeline_id, query=body.query,
        )
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        return result

    # stream=true: the run must exist (with a real run_id) before this
    # handler returns, since the client needs that id to open the SSE
    # connection — pipeline_runner.run_pipeline_for_query accepts a
    # pre-created run_id for exactly this case, so the background task
    # publishes events under the same id we hand back here.
    run_id = await create_pipeline_run(pool, body.pipeline_id, body.query)

    async def _emit(event: dict) -> None:
        await publish_event(redis_client, run_id, event)

    async def _background() -> None:
        await run_pipeline_for_query(
            pool=pool, llm_client=llm_client, arq_pool=arq_pool,
            pipeline_id=body.pipeline_id, query=body.query,
            emit_event=_emit, run_id=run_id,
        )

    asyncio.create_task(_background())
    return QueryQueuedResponse(run_id=run_id)


@router.get("/query/{run_id}/stream")
async def query_stream(request: Request, run_id: str):
    redis_client = request.app.state.redis

    async def event_generator():
        async for event in consume_events(redis_client, run_id):
            if await request.is_disconnected():
                break
            yield {"event": event.get("type", "message"), "data": json.dumps(event)}

    return EventSourceResponse(event_generator())
