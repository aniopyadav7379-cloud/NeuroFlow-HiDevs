import asyncio
import math
import time
import uuid
from typing import Any

import redis.asyncio as aioredis
from fastapi import HTTPException, Request

from backend.config import settings

_redis_client = None


def get_redis_client() -> Any:  # noqa: ANN401
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
    return _redis_client


# Lua Script for Token Bucket
TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2]) -- tokens per second
local now = tonumber(ARGV[3])
local requested = 1

local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(bucket[1])
local last_refill = tonumber(bucket[2])

if not tokens then
    tokens = capacity
    last_refill = now
else
    local elapsed = math.max(0, now - last_refill)
    local refill = math.floor(elapsed * refill_rate)
    if refill > 0 then
        tokens = math.min(capacity, tokens + refill)
        last_refill = now
    end
end

if tokens >= requested then
    tokens = tokens - requested
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
    redis.call('EXPIRE', key, math.ceil(capacity / refill_rate) * 2)
    return 1
else
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
    return 0
end
"""


async def wait_for_token(key: str, capacity: int, refill_rate: float, max_wait: int = 30) -> Any:  # noqa: ANN401
    client = get_redis_client()
    start_time = time.time()

    while time.time() - start_time < max_wait:
        now = time.time()
        allowed = await client.eval(TOKEN_BUCKET_SCRIPT, 1, key, capacity, refill_rate, now)
        if allowed == 1:
            return True
        await asyncio.sleep(0.5)

    raise TimeoutError(f"Rate limit token wait timeout exceeded for {key}")


async def consume_llm_token(provider: str) -> Any:  # noqa: ANN401
    if provider == "openai":
        capacity = 3000
        refill_rate = 50.0
    elif provider == "anthropic":
        capacity = 1000
        refill_rate = 15.0
    else:
        capacity = 1000
        refill_rate = 15.0

    key = f"rpb:{provider}:tokens"
    await wait_for_token(key, capacity, refill_rate)


async def consume_pipeline_token(pipeline_id: str, rpm: int) -> Any:  # noqa: ANN401
    key = f"rpb:pipeline:{pipeline_id}:tokens"
    capacity = rpm
    refill_rate = rpm / 60.0
    await wait_for_token(key, capacity, refill_rate)


# Lua script for sliding window API rate limiting
SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max_requests = tonumber(ARGV[3])
local member = ARGV[4]

local window_start = now - window
redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)
local current_requests = redis.call('ZCARD', key)

if current_requests < max_requests then
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, window)
    return -1
else
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    if #oldest >= 2 then
        local oldest_score = tonumber(oldest[2])
        return oldest_score + window - now
    else
        return window
    end
end
"""


def rate_limit_endpoint(max_requests: int, window_seconds: int) -> Any:  # noqa: ANN401
    async def dependency(request: Request) -> Any:  # noqa: ANN401
        client = get_redis_client()
        ip = request.client.host if request.client else "unknown"
        endpoint = request.url.path
        key = f"rate_limit:{endpoint}:{ip}"

        now = time.time()
        member = f"{now}:{uuid.uuid4().hex}"

        retry_after = await client.eval(
            SLIDING_WINDOW_SCRIPT, 1, key, now, window_seconds, max_requests, member
        )

        if retry_after != -1:
            raise HTTPException(
                status_code=429,
                detail="Too Many Requests",
                headers={
                    "Retry-After": str(
                        int(math.ceil(retry_after)) if retry_after > 0 else window_seconds
                    )
                },
            )

    return dependency
