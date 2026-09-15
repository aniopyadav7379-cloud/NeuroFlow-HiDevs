from typing import Any

import redis.asyncio as aioredis

from backend.config import settings
from backend.monitoring.metrics import queue_depth as queue_depth_metric

_redis_client = None


def get_redis_client() -> Any:  # noqa: ANN401
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
    return _redis_client


async def check_ingest_backpressure() -> Any:  # noqa: ANN401
    client = get_redis_client()

    # Track queue depth via ZCARD queue:ingest in Redis.
    # NOTE: this previously used LLEN, but arq's enqueue_job() (which is how
    # ingestion jobs actually get onto this queue - see backend/api/ingest.py)
    # stores queued job ids in a sorted set via ZADD, not a list. LLEN against a
    # sorted-set key raises a Redis WRONGTYPE error, which would have broken
    # backpressure checking (and every ingestion request behind it) the first
    # time a real job was ever enqueued.
    queue_depth = await client.zcard("queue:ingest")
    queue_depth_metric.set(queue_depth)

    if queue_depth > 100:
        return {
            "status_code": 503,
            "error": "ingestion_queue_full",
            "queue_depth": queue_depth,
            "retry_after": 30,
        }

    if queue_depth > 50:
        return {
            "status_code": 202,
            "warning": "high_queue_depth",
            "estimated_wait_minutes": queue_depth // 2,
        }

    return None
