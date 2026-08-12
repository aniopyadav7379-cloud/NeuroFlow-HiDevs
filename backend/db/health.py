"""
Independent connectivity checks used by GET /health.

Each check does real I/O against the dependency — none of these just
report "the client object exists". A check that only confirms a client was
constructed at startup would still say "ok" after the dependency died.
"""
import logging
import time

import asyncpg
import httpx
import redis.asyncio as redis

logger = logging.getLogger(__name__)


async def check_postgres(pool: asyncpg.Pool | None) -> bool:
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1")
        return result == 1
    except Exception:
        logger.exception("postgres health check failed")
        return False


async def check_redis(client: "redis.Redis | None") -> bool:
    if client is None:
        return False
    try:
        return bool(await client.ping())
    except Exception:
        logger.exception("redis health check failed")
        return False


async def check_mlflow(tracking_uri: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{tracking_uri}/health")
        return resp.status_code == 200
    except Exception:
        logger.exception("mlflow health check failed")
        return False


def _timed(ok: bool, started: float) -> dict:
    return {"status": "ok" if ok else "unreachable", "latency_ms": round((time.perf_counter() - started) * 1000, 1)}


async def check_postgres_timed(pool: asyncpg.Pool | None) -> dict:
    started = time.perf_counter()
    ok = await check_postgres(pool)
    return _timed(ok, started)


async def check_redis_timed(client: "redis.Redis | None") -> dict:
    started = time.perf_counter()
    ok = await check_redis(client)
    return _timed(ok, started)


async def check_mlflow_timed(tracking_uri: str) -> dict:
    started = time.perf_counter()
    ok = await check_mlflow(tracking_uri)
    return _timed(ok, started)
