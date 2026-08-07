"""
asyncpg connection pool lifecycle.

The pool is created exactly once, in main.py's lifespan handler, and stored
on app.state.pg_pool. Every request pulls a connection from that pool —
nothing in the request path calls asyncpg.connect() directly.
"""
import logging

import asyncpg

from backend.config import Settings

logger = logging.getLogger(__name__)


async def create_pool(settings: Settings) -> asyncpg.Pool:
    """Create the asyncpg pool. Call once, at app startup."""
    pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.postgres_pool_min_size,
        max_size=settings.postgres_pool_max_size,
        command_timeout=10,
    )
    logger.info(
        "postgres pool created (min=%s, max=%s)",
        settings.postgres_pool_min_size,
        settings.postgres_pool_max_size,
    )
    return pool


async def close_pool(pool: asyncpg.Pool | None) -> None:
    """Close the asyncpg pool. Call once, at app shutdown."""
    if pool is None:
        return
    await pool.close()
    logger.info("postgres pool closed")
