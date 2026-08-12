"""
Two rate-limiting patterns, both implemented as Lua scripts run via Redis
EVAL — a plain GET-then-SET from Python would race under concurrent
requests (two requests could both read "1 token left" and both proceed),
so the check-and-consume has to happen atomically inside Redis itself.

  - Token bucket: continuous refill, used for LLM provider limits (global
    and per-pipeline) — a burst is fine as long as the average rate
    over time stays under the provider's actual limit.
  - Sliding window log: used for user-facing API endpoints (/ingest,
    /query) — a hard cap on requests-per-IP within a rolling window.
"""
import asyncio
import logging
import time
import uuid

logger = logging.getLogger("neuroflow.resilience.rate_limiter")

# ── token bucket ──────────────────────────────────────────────────────
# KEYS[1] = tokens key, KEYS[2] = last_refill key
# ARGV[1] = capacity, ARGV[2] = refill_rate_per_sec, ARGV[3] = now, ARGV[4] = cost
_TOKEN_BUCKET_SCRIPT = """
local tokens_key = KEYS[1]
local last_refill_key = KEYS[2]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])

local tokens = tonumber(redis.call('GET', tokens_key))
if tokens == nil then tokens = capacity end
local last_refill = tonumber(redis.call('GET', last_refill_key))
if last_refill == nil then last_refill = now end

local elapsed = math.max(0, now - last_refill)
tokens = math.min(capacity, tokens + elapsed * refill_rate)

local allowed = 0
if tokens >= cost then
    tokens = tokens - cost
    allowed = 1
end

redis.call('SET', tokens_key, tostring(tokens), 'EX', 3600)
redis.call('SET', last_refill_key, tostring(now), 'EX', 3600)

return {allowed, tostring(tokens)}
"""


class RateLimitExceeded(Exception):
    def __init__(self, message: str, retry_after: float):
        super().__init__(message)
        self.retry_after = retry_after


class TokenBucketRateLimiter:
    def __init__(self, redis_client):
        self.redis = redis_client

    async def _try_acquire(
        self, key_prefix: str, capacity: float, refill_rate_per_sec: float, cost: float = 1.0
    ) -> tuple[bool, float]:
        tokens_key = f"{key_prefix}:tokens"
        last_refill_key = f"{key_prefix}:last_refill"
        allowed, remaining = await self.redis.eval(
            _TOKEN_BUCKET_SCRIPT, 2, tokens_key, last_refill_key,
            capacity, refill_rate_per_sec, time.time(), cost,
        )
        return bool(int(allowed)), float(remaining)

    async def acquire(
        self,
        key_prefix: str,
        capacity: float,
        refill_rate_per_sec: float,
        *,
        cost: float = 1.0,
        wait: bool = True,
        max_wait_seconds: float = 30.0,
    ) -> None:
        """Blocks (briefly, with backoff) until a token is available, up
        to max_wait_seconds, then raises RateLimitExceeded. If wait=False,
        raises immediately on the first failed attempt instead."""
        started = time.monotonic()
        backoff = 0.05
        while True:
            allowed, remaining = await self._try_acquire(key_prefix, capacity, refill_rate_per_sec, cost)
            if allowed:
                return
            if not wait:
                raise RateLimitExceeded(f"rate limit exceeded for '{key_prefix}'", retry_after=1.0 / refill_rate_per_sec)

            elapsed = time.monotonic() - started
            if elapsed >= max_wait_seconds:
                raise RateLimitExceeded(
                    f"rate limit exceeded for '{key_prefix}' after waiting {max_wait_seconds}s",
                    retry_after=1.0 / refill_rate_per_sec,
                )
            await asyncio.sleep(min(backoff, max_wait_seconds - elapsed))
            backoff = min(backoff * 2, 1.0)


# Provider limits — OpenAI's published gpt-4o-mini limit is 3,000 RPM;
# 3000/60 = 50 tokens/sec refill, matching the task spec exactly.
PROVIDER_RATE_LIMITS = {
    "openai": {"capacity": 3000, "refill_rate_per_sec": 50.0},
}


async def acquire_global_provider_tokens(redis_client, provider: str) -> None:
    limits = PROVIDER_RATE_LIMITS.get(provider)
    if limits is None:
        return  # no configured limit for this provider — don't block on nothing
    limiter = TokenBucketRateLimiter(redis_client)
    await limiter.acquire(f"rpb:{provider}", limits["capacity"], limits["refill_rate_per_sec"])


async def acquire_pipeline_tokens(redis_client, pipeline_id: str, rate_limit_rpm: int) -> None:
    limiter = TokenBucketRateLimiter(redis_client)
    await limiter.acquire(
        f"rpb:pipeline:{pipeline_id}",
        capacity=rate_limit_rpm,
        refill_rate_per_sec=rate_limit_rpm / 60.0,
    )


# ── sliding window (API endpoint rate limiting) ──────────────────────
# KEYS[1] = zset key
# ARGV[1] = now, ARGV[2] = window_seconds, ARGV[3] = limit, ARGV[4] = member
_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)

local allowed = 0
if count < limit then
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, window)
    allowed = 1
    count = count + 1
end

return {allowed, count}
"""


class SlidingWindowRateLimiter:
    def __init__(self, redis_client):
        self.redis = redis_client

    async def check(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = time.time()
        member = f"{now}:{uuid.uuid4().hex[:8]}"  # unique per call even at identical timestamps
        allowed, count = await self.redis.eval(
            _SLIDING_WINDOW_SCRIPT, 1, key, now, window_seconds, limit, member
        )
        return bool(int(allowed)), int(count)
