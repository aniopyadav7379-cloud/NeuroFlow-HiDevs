"""
Worker liveness tracking: arq doesn't natively expose "how many worker
processes are currently connected" (it's designed around queue names, not
a worker registry), so this implements a small heartbeat pattern
ourselves — each worker process registers a TTL'd Redis key on startup
and refreshes it periodically via a cron job; GET /health counts live
heartbeat keys to report worker_count. A key that isn't refreshed in time
expires on its own, so a crashed worker (no clean shutdown) still ages
out instead of counting forever.
"""
import logging
import uuid

logger = logging.getLogger("neuroflow.resilience.worker_heartbeat")

HEARTBEAT_KEY_PREFIX = "workers:heartbeat:"
HEARTBEAT_TTL_SECONDS = 30
HEARTBEAT_REFRESH_SECONDS = 10  # must be well under the TTL


def new_worker_id() -> str:
    return uuid.uuid4().hex[:12]


async def register_heartbeat(redis_client, worker_id: str) -> None:
    await redis_client.set(f"{HEARTBEAT_KEY_PREFIX}{worker_id}", "1", ex=HEARTBEAT_TTL_SECONDS)


async def deregister_heartbeat(redis_client, worker_id: str) -> None:
    await redis_client.delete(f"{HEARTBEAT_KEY_PREFIX}{worker_id}")


async def get_worker_count(redis_client) -> int:
    count = 0
    cursor = 0
    while True:
        cursor, keys = await redis_client.scan(cursor, match=f"{HEARTBEAT_KEY_PREFIX}*", count=100)
        count += len(keys)
        if cursor == 0:
            break
    return count
