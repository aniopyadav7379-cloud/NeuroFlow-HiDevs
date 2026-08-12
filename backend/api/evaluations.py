"""
GET /evaluations/stream — real-time SSE feed of evaluation results.
Subscribes to the Redis pub/sub channel evaluation/judge.py publishes to
after every write, and forwards each message to connected clients.

Pub/sub, not a Redis Stream here (contrast with pipelines/generation/
events.py's deliberate choice of Streams over pub/sub for the per-run
SSE): a dropped message on this channel just means a late-connecting
dashboard misses one feed card, not a broken user-facing generation flow
— the durability Streams buy isn't worth the extra bookkeeping for a
best-effort live feed that GET /pipelines/{id}/runs can always backfill.
"""
import asyncio
import json
import logging

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger("neuroflow.api.evaluations")
router = APIRouter()

EVALUATIONS_CHANNEL = "evaluations:new"


@router.get("/evaluations/stream")
async def evaluations_stream(request: Request):
    redis_client = request.app.state.redis

    async def event_generator():
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(EVALUATIONS_CHANNEL)
        try:
            while True:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
                if message is None:
                    yield {"event": "keepalive", "data": "{}"}
                    continue
                yield {"event": "evaluation", "data": message["data"]}
        finally:
            await pubsub.unsubscribe(EVALUATIONS_CHANNEL)
            await pubsub.aclose()

    return EventSourceResponse(event_generator())
