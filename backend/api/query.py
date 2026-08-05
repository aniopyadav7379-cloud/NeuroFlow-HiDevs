"""
POST /query and GET /query/{run_id}/stream — the generation-facing HTTP
surface. POST creates the pipeline_runs row and either runs the whole
pipeline synchronously (stream=false) or kicks off a background task and
returns immediately (stream=true); GET tails that background task's
events over SSE.
"""
import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from pipelines.generation.events import consume_events, publish_event
from pipelines.generation.generator import create_pipeline_run, generate, mark_run_failed
from pipelines.retrieval.pipeline import RetrievalPipeline

logger = logging.getLogger("neuroflow.api.query")
router = APIRouter()


class QueryRequest(BaseModel):
    query: str
    pipeline_id: str
    stream: bool = True
    use_chain_of_thought: bool = False


class QueryQueuedResponse(BaseModel):
    run_id: str
    status: str = "queued"


async def _run_pipeline(
    app,
    run_id: str,
    pipeline_id: str,
    query: str,
    use_chain_of_thought: bool,
    *,
    emit_events: bool,
):
    """Shared by both the streaming (background task, events published to
    Redis) and non-streaming (awaited inline, events collected in a list)
    paths, so retrieval/generation logic exists exactly once."""
    pool = app.state.pg_pool
    llm_client = app.state.llm_client
    arq_pool = app.state.arq_pool
    redis_client = app.state.redis

    collected_events = []

    async def _emit(event: dict):
        collected_events.append(event)
        if emit_events:
            await publish_event(redis_client, run_id, event)

    await _emit({"type": "retrieval_start"})

    retrieval_pipeline = RetrievalPipeline(pool, llm_client)
    try:
        result = await retrieval_pipeline.retrieve(query)
    except Exception:
        logger.exception("retrieval failed for run_id=%s", run_id)
        await mark_run_failed(pool, run_id, error="retrieval failed")
        await _emit({"type": "error", "message": "retrieval failed"})
        return collected_events

    source_docs = sorted({
        s["document_name"] for s in result.assembled.sources if s.get("document_name")
    })
    await _emit({
        "type": "retrieval_complete",
        "chunk_count": len(result.assembled.chunks_used),
        "sources": source_docs,
    })

    try:
        async for event in generate(
            pool=pool, llm_client=llm_client, arq_pool=arq_pool,
            run_id=run_id, pipeline_id=pipeline_id, query=query,
            query_type=result.processed_query.query_type,
            assembled=result.assembled,
            use_chain_of_thought=use_chain_of_thought,
        ):
            await _emit(event)
    except Exception:
        logger.exception("generation failed for run_id=%s", run_id)
        await mark_run_failed(pool, run_id, error="generation failed")
        await _emit({"type": "error", "message": "generation failed"})

    return collected_events


@router.post("/query")
async def query(request: Request, body: QueryRequest):
    pool = request.app.state.pg_pool
    run_id = await create_pipeline_run(pool, body.pipeline_id, body.query)

    if not body.stream:
        events = await _run_pipeline(
            request.app, run_id, body.pipeline_id, body.query,
            body.use_chain_of_thought, emit_events=False,
        )
        error_event = next((e for e in events if e["type"] == "error"), None)
        if error_event:
            raise HTTPException(status_code=500, detail=error_event["message"])

        done_event = next(e for e in events if e["type"] == "done")
        retrieval_complete = next(e for e in events if e["type"] == "retrieval_complete")
        generation_text = "".join(e["delta"] for e in events if e["type"] == "token")

        return {
            "run_id": run_id,
            "generation": generation_text,
            "citations": done_event["citations"],
            "sources": retrieval_complete["sources"],
            "chunk_count": retrieval_complete["chunk_count"],
        }

    # stream=true: return run_id immediately, run the pipeline in the
    # background, publish events for GET /query/{run_id}/stream to relay.
    asyncio.create_task(
        _run_pipeline(request.app, run_id, body.pipeline_id, body.query, body.use_chain_of_thought, emit_events=True)
    )
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
