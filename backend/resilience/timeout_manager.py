import asyncio
import logging
import time
import uuid
from typing import Any

import redis.asyncio as aioredis

from backend.config import settings

logger = logging.getLogger(__name__)

_redis_client = None


def get_redis_client() -> Any:  # noqa: ANN401
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
    return _redis_client


class TimeoutManager:
    timeouts = {
        "embedding": 10,  # seconds
        "chat_completion": 60,
        "reranking": 15,
        "evaluation": 120,  # evaluation is slower (multiple LLM calls)
        "file_extraction": 30,
        "url_fetch": 15,
    }

    @classmethod
    async def _update_latency(cls, task_type: str, latency: float) -> Any:  # noqa: ANN401
        client = get_redis_client()
        now = time.time()

        # Push to list (last 1000 calls)
        await client.lpush(f"latencies:{task_type}", str(latency))
        await client.ltrim(f"latencies:{task_type}", 0, 999)

        # Check if we need to recalculate p95 (cache it for 30 seconds to avoid sorting on every call)  # noqa: E501
        cached_p95 = await client.get(f"p95_cached:{task_type}")
        if not cached_p95:
            latencies = await client.lrange(f"latencies:{task_type}", 0, -1)
            if len(latencies) >= 10:  # Need at least a few samples to be meaningful
                latencies = [float(x) for x in latencies]
                latencies.sort()

                idx = int(len(latencies) * 0.95)
                p95 = latencies[idx]

                # Cache for 30 seconds
                await client.set(f"p95_cached:{task_type}", str(p95), ex=30)

                # Store history for trend analysis over the last hour
                # Score is timestamp, value is "p95:uuid" to ensure uniqueness
                await client.zadd(f"p95_history:{task_type}", {f"{p95}:{uuid.uuid4().hex}": now})

                # Clean up old history (> 1 hour)
                await client.zremrangebyscore(f"p95_history:{task_type}", "-inf", now - 3600)

                # Check for increasing trend
                history = await client.zrange(f"p95_history:{task_type}", 0, 0, withscores=True)
                if history:
                    oldest_p95 = float(history[0][0].split(":")[0])
                    oldest_time = history[0][1]

                    # If we have data spanning at least 15 minutes, and current p95 is significantly higher (e.g. 50% higher)  # noqa: E501
                    if now - oldest_time > 900 and p95 > oldest_p95 * 1.5:
                        logger.warning(
                            f"Increasing p95 latency trend detected for {task_type}! Old p95: {oldest_p95:.2f}s, Current p95: {p95:.2f}s"  # noqa: E501
                        )

    @classmethod
    async def get_timeout(cls, task_type: str) -> float:
        base_timeout = cls.timeouts.get(task_type, 60.0)
        client = get_redis_client()
        cached_p95 = await client.get(f"p95_cached:{task_type}")

        if cached_p95:
            p95 = float(cached_p95)
            # Automatically adjust timeout to p95 * 1.5
            # We enforce a sensible floor so it doesn't get ridiculously small and cause false timeouts  # noqa: E501
            return max(p95 * 1.5, base_timeout * 0.25)

        return base_timeout

    @classmethod
    async def run(cls, task_type: str, coro: Any) -> Any:  # noqa: ANN401
        timeout = await cls.get_timeout(task_type)
        start_time = time.time()

        try:
            result = await asyncio.wait_for(coro, timeout=timeout)

            # Record successful latency asynchronously
            latency = time.time() - start_time
            asyncio.create_task(cls._update_latency(task_type, latency))

            return result

        except TimeoutError as e:
            logger.error(f"Timeout occurred for task type: {task_type} after {timeout:.2f}s")
            client = get_redis_client()
            await client.incr(f"timeouts:{task_type}")
            raise TimeoutError(f"Task {task_type} timed out after {timeout:.2f} seconds") from e
