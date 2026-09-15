import asyncio
import logging
from typing import Any

from backend.db.pool import create_pool, get_pool

logger = logging.getLogger(__name__)




async def main() -> Any:  # noqa: ANN401
    await create_pool()
    pool = get_pool()
    async with pool.acquire() as conn:
        logger.info("Applying Task 08 migrations...")

        # Add columns to pipelines
        try:
            await conn.execute("ALTER TABLE pipelines ADD COLUMN version INT DEFAULT 1")
            logger.info("Added version column to pipelines.")
        except Exception as e:
            logger.info(f"Skipped pipelines.version: {e}")

        try:
            await conn.execute(
                "ALTER TABLE pipelines ADD COLUMN status VARCHAR(20) DEFAULT 'active'"
            )
            logger.info("Added status column to pipelines.")
        except Exception as e:
            logger.info(f"Skipped pipelines.status: {e}")

        # Create pipeline_versions table
        try:
            await conn.execute("""
            CREATE TABLE pipeline_versions (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                pipeline_id UUID NOT NULL REFERENCES pipelines(id),
                version INT NOT NULL,
                config JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """)
            logger.info("Created pipeline_versions table.")
            # Seed the pipeline_versions table with existing pipelines
            await conn.execute("""
            INSERT INTO pipeline_versions (pipeline_id, version, config, created_at)
            SELECT id, 1, config, created_at FROM pipelines
            """)
        except Exception as e:
            logger.info(f"Skipped pipeline_versions creation: {e}")

        # Modify pipeline_runs
        try:
            await conn.execute("ALTER TABLE pipeline_runs ADD COLUMN pipeline_version INT")
            logger.info("Added pipeline_version column to pipeline_runs.")
        except Exception as e:
            logger.info(f"Skipped pipeline_runs.pipeline_version: {e}")

        try:
            await conn.execute("ALTER TABLE pipeline_runs ADD COLUMN retrieval_latency_ms INT")
            logger.info("Added retrieval_latency_ms column to pipeline_runs.")
        except Exception as e:
            logger.info(f"Skipped pipeline_runs.retrieval_latency_ms: {e}")

        # Add metadata column to pipelines if needed? No, config is JSONB.

        logger.info("Task 08 migrations complete.")


if __name__ == "__main__":
    asyncio.run(main())
