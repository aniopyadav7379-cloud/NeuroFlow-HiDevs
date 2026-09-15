from typing import Any

import asyncpg

from backend.config import settings

pool = None


async def create_pool() -> Any:  # noqa: ANN401
    global pool
    
    server_settings = {}
    if settings.env_prefix:
        server_settings["search_path"] = f"{settings.env_prefix}, public"
        
    pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        server_settings=server_settings
    )


async def close_pool() -> Any:  # noqa: ANN401
    global pool
    if pool:
        await pool.close()
        pool = None


def get_pool() -> Any:  # noqa: ANN401
    return pool
