import time

import httpx
import redis.asyncio as redis

from backend.config import settings
from backend.db.pool import get_pool


async def check_postgres() -> dict:  # type: ignore
    start = time.perf_counter()
    pool = get_pool()
    if not pool:
        return {"status": "error", "latency_ms": 0}
    try:
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        latency = int((time.perf_counter() - start) * 1000)
        return {"status": "ok", "latency_ms": latency}
    except Exception:
        return {"status": "error", "latency_ms": 0}


async def check_redis() -> dict:  # type: ignore
    start = time.perf_counter()
    try:
        r = redis.Redis(
            host=settings.redis_host, port=settings.redis_port, password=settings.redis_password
        )
        await r.ping()
        await r.close()
        latency = int((time.perf_counter() - start) * 1000)
        return {"status": "ok", "latency_ms": latency}
    except Exception:
        return {"status": "error", "latency_ms": 0}


async def check_mlflow() -> dict:  # type: ignore
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{settings.mlflow_uri}/ping", timeout=2.0)
            latency = int((time.perf_counter() - start) * 1000)
            if response.status_code == 200:
                return {"status": "ok", "latency_ms": latency}
            else:
                return {"status": "error", "latency_ms": latency}
    except Exception:
        return {"status": "error", "latency_ms": 0}
