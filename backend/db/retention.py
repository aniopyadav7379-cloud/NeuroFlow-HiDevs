import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.db.pool import get_pool

logger = structlog.get_logger(__name__)

async def run_data_retention_policy() -> None:
    """
    Executes the data retention policy to delete old pipeline runs, evaluations, and chunks.
    """
    pool = get_pool()
    if not pool:
        logger.error("Database pool not initialized. Skipping data retention job.")
        return

    logger.info("Starting data retention cleanup job.")
    
    try:
        async with pool.acquire() as conn:
            # 1. Delete pipeline_runs older than 90 days where status='complete' 
            # and no evaluations row, unless flagged
            q1 = """
                DELETE FROM pipeline_runs
                WHERE created_at < NOW() - INTERVAL '90 days'
                AND id NOT IN (SELECT run_id FROM evaluations)
                AND (metadata->>'flagged' IS NULL OR metadata->>'flagged' != 'true')
            """
            result1 = await conn.execute(q1)
            runs_deleted = int(result1.split(" ")[-1]) if result1 else 0

            # 2. Delete evaluations older than 180 days
            q2 = """
                DELETE FROM evaluations
                WHERE evaluated_at < NOW() - INTERVAL '180 days'
            """
            result2 = await conn.execute(q2)
            evals_deleted = int(result2.split(" ")[-1]) if result2 else 0

            # 3. Delete chunks for documents with status='archived'
            q3 = """
                DELETE FROM chunks
                WHERE document_id IN (
                    SELECT id FROM documents WHERE status = 'archived'
                )
            """
            result3 = await conn.execute(q3)
            chunks_deleted = int(result3.split(" ")[-1]) if result3 else 0

            logger.info(
                "Data retention cleanup completed successfully.",
                pipeline_runs_deleted=runs_deleted,
                evaluations_deleted=evals_deleted,
                archived_chunks_deleted=chunks_deleted
            )
            
    except Exception as e:
        logger.error("Failed to execute data retention job.", error=str(e))

scheduler = AsyncIOScheduler()

def start_retention_scheduler() -> None:
    # Run daily at 3:00 AM
    scheduler.add_job(run_data_retention_policy, 'cron', hour=3, minute=0)
    scheduler.start()
    logger.info("Data retention APScheduler started. Configured to run daily at 03:00.")

def stop_retention_scheduler() -> None:
    scheduler.shutdown(wait=False)
    logger.info("Data retention APScheduler stopped.")
