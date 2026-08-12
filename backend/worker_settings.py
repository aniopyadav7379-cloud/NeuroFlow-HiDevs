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
from arq import cron
from arq.connections import RedisSettings

from backend.config import get_settings
from backend.db.migrations import ensure_schema
from backend.db.pool import close_pool, create_pool
from backend.providers.client import build_client
from backend.resilience.worker_heartbeat import (
    deregister_heartbeat,
    new_worker_id,
    register_heartbeat,
)
from evaluation.worker import evaluate_generation_job
from pipelines.finetuning.job_manager import poll_finetune_jobs_job
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

    # GET /health's worker_count reads these heartbeat keys — see
    # backend/resilience/worker_heartbeat.py for why arq itself doesn't
    # give us this directly.
    ctx["worker_id"] = new_worker_id()
    await register_heartbeat(ctx["redis"], ctx["worker_id"])

    logger.info("worker startup complete (worker_id=%s)", ctx["worker_id"])


async def shutdown(ctx: dict) -> None:
    redis_client = ctx.get("redis")
    if redis_client is not None:
        worker_id = ctx.get("worker_id")
        if worker_id is not None:
            await deregister_heartbeat(redis_client, worker_id)
        await redis_client.aclose()
    await close_pool(ctx.get("pg_pool"))
    logger.info("worker shutdown complete")


async def refresh_heartbeat_job(ctx: dict) -> None:
    redis_client = ctx.get("redis")
    worker_id = ctx.get("worker_id")
    if redis_client is not None and worker_id is not None:
        await register_heartbeat(redis_client, worker_id)  # SET with EX again = refresh


class WorkerSettings:
    functions = [process_document_job, evaluate_generation_job]
    cron_jobs = [
        # Task 39: poll active fine-tuning jobs' provider status every 60
        # seconds. arq's cron scheduling is second-granular, not
        # interval-granular — second={0} means "once per minute, at :00",
        # which is what "every 60 seconds" means in practice here.
        cron(poll_finetune_jobs_job, second=0, unique=True),
        # Task 40: refresh this worker's heartbeat well inside its TTL
        # (30s) so GET /health's worker_count stays accurate.
        cron(refresh_heartbeat_job, second={0, 10, 20, 30, 40, 50}, unique=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    # redis_settings is resolved lazily in backend/worker.py (needs
    # get_settings() first) — set there before run_worker() is called.
    redis_settings: RedisSettings | None = None
    max_jobs = 10
    job_timeout = 300  # seconds; PDF OCR / large-doc embedding can be slow
    keep_result = 3600  # seconds to retain job results for GET-status style checks
