"""
arq WorkerSettings for the single shared NeuroFlow worker process — every
subsystem's background job function is registered here. Originally lived
at pipelines/ingestion/worker_settings.py when ingestion was the only
subsystem with jobs; relocated here once evaluation (Task 37) needed to
register its own function too, since "the ingestion worker settings"
was no longer an accurate name for a file evaluation also depends on.

Run via backend/worker.py (the entrypoint infra/docker-compose.yml's
`worker` service invokes as `python -m worker`), or directly with
`arq backend.worker_settings.WorkerSettings`.
"""
import logging

import redis.asyncio as redis
from arq.connections import RedisSettings

from backend.config import get_settings
from backend.db.migrations import ensure_schema
from backend.db.pool import close_pool, create_pool
from backend.providers.client import build_client
from evaluation.worker import evaluate_generation_job
from pipelines.ingestion.pipeline import process_document_job

logger = logging.getLogger("neuroflow.worker")


async def startup(ctx: dict) -> None:
    settings = get_settings()
    ctx["settings"] = settings

    ctx["pg_pool"] = await create_pool(settings)
    await ensure_schema(ctx["pg_pool"])

    ctx["redis"] = redis.from_url(settings.redis_url, decode_responses=True)

    try:
        ctx["llm_client"] = build_client(settings, ctx["redis"])
    except RuntimeError as e:
        logger.error("LLM client not initialized in worker: %s", e)
        ctx["llm_client"] = None

    logger.info("worker startup complete")


async def shutdown(ctx: dict) -> None:
    redis_client = ctx.get("redis")
    if redis_client is not None:
        await redis_client.aclose()
    await close_pool(ctx.get("pg_pool"))
    logger.info("worker shutdown complete")


class WorkerSettings:
    functions = [process_document_job, evaluate_generation_job]
    on_startup = startup
    on_shutdown = shutdown
    # redis_settings is resolved lazily in backend/worker.py (needs
    # get_settings() first) — set there before run_worker() is called.
    redis_settings: RedisSettings | None = None
    max_jobs = 10
    job_timeout = 300  # seconds; PDF OCR / large-doc embedding can be slow
    keep_result = 3600  # seconds to retain job results for GET-status style checks
