"""
Ingestion job queue, backed by arq rather than raw Redis list operations
(LPUSH/BRPOP) — arq gives structured job IDs, retries, timeouts, and result
tracking on top of the same Redis instance, instead of NeuroFlow having to
hand-roll that on top of a plain list.
"""
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

JOB_FUNCTION_NAME = "process_document_job"


async def create_arq_pool(redis_url: str) -> ArqRedis:
    """Called once at API/worker startup; the returned pool is reused for
    every enqueue (API side) for the process lifetime."""
    return await create_pool(RedisSettings.from_dsn(redis_url))


async def enqueue_ingestion_job(
    arq_pool: ArqRedis,
    *,
    document_id: str,
    file_path: str | None,
    source_type: str,
    pipeline_id: str | None = None,
) -> str:
    job = await arq_pool.enqueue_job(
        JOB_FUNCTION_NAME,
        document_id=document_id,
        file_path=file_path,
        source_type=source_type,
        pipeline_id=pipeline_id,
    )
    if job is None:
        # arq returns None if a job with the same _job_id is already
        # queued/running — we don't set a custom _job_id here, so this
        # path is effectively unreachable, but fail loudly rather than
        # silently returning a fake ID if that ever changes.
        raise RuntimeError(f"failed to enqueue ingestion job for document_id={document_id}")
    return job.job_id
