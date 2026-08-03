"""
Background worker entrypoint (`python -m worker`), invoked by the
`worker` service in infra/docker-compose.yml.

This is the process that will run the Ingestion Subsystem's job queue
consumer, the Evaluation Subsystem's async scorer, and the Fine-Tuning
Subsystem's mining job (docs/architecture.md §1, §4, §5) — implemented in
later tasks. For now it's a minimal, correctly-wired skeleton: it builds
its own Postgres pool and Redis client (workers don't share the API
process's app.state) and confirms both are reachable before idling, so
`docker compose up` proves the whole stack — including this service — is
wired correctly, per this task's checklist.
"""
import asyncio
import logging

import redis.asyncio as redis

from backend.config import get_settings
from backend.db.health import check_postgres, check_redis
from backend.db.pool import close_pool, create_pool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("neuroflow.worker")


async def main() -> None:
    settings = get_settings()
    pool = await create_pool(settings)
    redis_client = redis.from_url(settings.redis_url, decode_responses=True)

    postgres_ok = await check_postgres(pool)
    redis_ok = await check_redis(redis_client)
    logger.info("worker connectivity check: postgres=%s redis=%s", postgres_ok, redis_ok)

    try:
        # Placeholder loop — replaced by the real queue consumer in the
        # Ingestion/Evaluation/Fine-Tuning task implementations.
        while True:
            await asyncio.sleep(30)
            logger.info("worker heartbeat")
    finally:
        await redis_client.aclose()
        await close_pool(pool)


if __name__ == "__main__":
    asyncio.run(main())
