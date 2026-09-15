import logging
import os
from typing import Any

from backend.db.pool import get_pool

logger = logging.getLogger(__name__)




async def run_migrations() -> Any:  # noqa: ANN401
    pool = get_pool()
    schema_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "infra", "init", "001_schema.sql"
    )

    # Read the schema file
    try:
        with open(schema_path) as f:  # noqa: ASYNC230
            schema_sql = f.read()
    except Exception as e:
        logger.info(f"Error reading schema file: {e}")
        return

    # In a real app we'd use Alembic or similar, but for now we'll just check if the documents table exists  # noqa: E501
    async with pool.acquire() as conn:
        try:
            # Check if applied
            val = await conn.fetchval("SELECT to_regclass('public.documents')")
            if not val:
                logger.info("Applying 001_schema.sql")
                await conn.execute(schema_sql)
            else:
                logger.info("Schema already applied.")

            # Add prompt column to pipeline_runs if it doesn't exist
            logger.info("Applying ALTER TABLE for pipeline_runs prompt and metadata columns")
            await conn.execute("ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS prompt TEXT;")
            await conn.execute(
                "ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';"
            )

            logger.info("Applying ALTER TABLE for evaluations metadata column")
            await conn.execute(
                "ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';"
            )

            logger.info("Applying CREATE TABLE for pipeline_anomalies")
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_anomalies (
              id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
              pipeline_id UUID NOT NULL REFERENCES pipelines(id),
              run_id UUID REFERENCES pipeline_runs(id),
              score FLOAT,
              rolling_mean FLOAT,
              rolling_stddev FLOAT,
              suggestions JSONB,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """)
        except Exception as e:
            logger.info(f"Migration error: {e}")
