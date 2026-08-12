"""
FastAPI dependency factory wrapping SlidingWindowRateLimiter for
user-facing endpoint rate limiting (POST /ingest, POST /query). Kept
separate from rate_limiter.py so that module stays framework-agnostic —
this is the only file that imports fastapi.
"""
from fastapi import HTTPException, Request

from backend.resilience.rate_limiter import SlidingWindowRateLimiter


def _client_ip(request: Request) -> str:
    # Trust X-Forwarded-For's first hop if present (typical behind a
    # reverse proxy/load balancer); fall back to the direct connection.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(limit: int, window_seconds: int, *, key_prefix: str):
    """Returns a FastAPI dependency enforcing `limit` requests per
    `window_seconds` per client IP, scoped by `key_prefix` (so /ingest and
    /query have independent limits even for the same IP)."""

    async def _dependency(request: Request) -> None:
        redis_client = request.app.state.redis
        limiter = SlidingWindowRateLimiter(redis_client)
        ip = _client_ip(request)
        key = f"ratelimit:{key_prefix}:{ip}"

        allowed, count = await limiter.check(key, limit, window_seconds)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too Many Requests",
                headers={"Retry-After": str(window_seconds)},
            )

    return _dependency
