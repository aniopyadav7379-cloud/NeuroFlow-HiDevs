"""
Ingestion backpressure: NeuroFlow tracks its own queue-depth counter
(`queue:ingest:depth`) rather than reading arq's internal Redis key
structure directly — arq doesn't document that structure as a stable
public API (it uses different keys for its immediate-job list vs its
scheduled/delayed sorted set, and that's an implementation detail that
could change between arq versions). Incrementing on enqueue
(backend/api/ingest.py) and decrementing when a job actually starts
(pipelines/ingestion/pipeline.py) gives an equally accurate "how many
jobs are waiting" count without depending on arq internals.
"""
import logging
from dataclasses import dataclass

logger = logging.getLogger("neuroflow.resilience.backpressure")

from backend.monitoring.metrics import queue_depth as queue_depth_gauge

QUEUE_DEPTH_KEY = "queue:ingest:depth"

QUEUE_FULL_THRESHOLD = 100
QUEUE_HIGH_THRESHOLD = 50

# Rough heuristic for the warning's estimated_wait_minutes — the real
# figure depends on document size/type mix, which isn't known at enqueue
# time; this is a coarse average, not a promise.
ASSUMED_SECONDS_PER_DOCUMENT = 20


@dataclass
class BackpressureDecision:
    allowed: bool
    status_code: int = 200
    body: dict | None = None


async def get_queue_depth(redis_client) -> int:
    depth = await redis_client.get(QUEUE_DEPTH_KEY)
    return int(depth) if depth else 0


async def increment_queue_depth(redis_client) -> None:
    new_value = await redis_client.incr(QUEUE_DEPTH_KEY)
    queue_depth_gauge.set(new_value)


async def decrement_queue_depth(redis_client) -> None:
    # Never let the counter go negative (e.g. a job retried after a crash
    # that already decremented once) — floor at 0 rather than track a
    # meaningless negative "depth".
    new_value = await redis_client.decr(QUEUE_DEPTH_KEY)
    if new_value < 0:
        await redis_client.set(QUEUE_DEPTH_KEY, 0)
        new_value = 0
    queue_depth_gauge.set(new_value)


async def check_backpressure(redis_client) -> BackpressureDecision:
    depth = await get_queue_depth(redis_client)

    if depth > QUEUE_FULL_THRESHOLD:
        return BackpressureDecision(
            allowed=False,
            status_code=503,
            body={"error": "ingestion_queue_full", "queue_depth": depth, "retry_after": 30},
        )

    if depth > QUEUE_HIGH_THRESHOLD:
        estimated_wait_minutes = round((depth * ASSUMED_SECONDS_PER_DOCUMENT) / 60, 1)
        return BackpressureDecision(
            allowed=True,
            status_code=202,
            body={"warning": "high_queue_depth", "queue_depth": depth, "estimated_wait_minutes": estimated_wait_minutes},
        )

    return BackpressureDecision(allowed=True, status_code=200)
