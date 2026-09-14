import time
from typing import Any

import redis.asyncio as aioredis

from backend.config import settings
from backend.monitoring.metrics import active_circuit_breakers_open, circuit_breaker_trips


class CircuitOpenError(Exception):
    pass


_redis_client = None


def get_redis_client() -> Any:  # noqa: ANN401
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
    return _redis_client


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_max_calls: int = 3,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self.state_key = f"circuit:{name}:state"
        self.failure_key = f"circuit:{name}:failure_count"
        self.opened_at_key = f"circuit:{name}:opened_at"
        self.half_open_count_key = f"circuit:{name}:half_open_count"

        self.redis = get_redis_client()

    async def __aenter__(self) -> Any:  # noqa: ANN401
        state = await self.redis.get(self.state_key) or "closed"

        if state == "open":
            opened_at_str = await self.redis.get(self.opened_at_key)
            if opened_at_str:
                opened_at = float(opened_at_str)
                if time.time() - opened_at > self.recovery_timeout:
                    # Transition to half-open
                    await self.redis.set(self.state_key, "half-open")
                    await self.redis.set(self.half_open_count_key, 0)
                    state = "half-open"
                else:
                    raise CircuitOpenError(f"Circuit {self.name} is OPEN")
            else:
                # Fallback if opened_at is missing for some reason
                raise CircuitOpenError(f"Circuit {self.name} is OPEN")

        if state == "half-open":
            count = await self.redis.incr(self.half_open_count_key)
            if count > self.half_open_max_calls:
                raise CircuitOpenError(
                    f"Circuit {self.name} is HALF_OPEN and testing limit reached"
                )

        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:  # noqa: ANN401
        if exc_type is None:
            # Success
            state = await self.redis.get(self.state_key)
            if state == "half-open":
                # If any succeed -> closed
                await self.redis.set(self.state_key, "closed")
                await self.redis.set(self.failure_key, 0)
                active_circuit_breakers_open.dec()
            elif state == "closed":
                # Reset failures on success
                await self.redis.set(self.failure_key, 0)
        else:
            # We ignore CircuitOpenError itself as a failure that increments count
            if isinstance(exc_val, CircuitOpenError):
                return False

            # Failure
            state = await self.redis.get(self.state_key) or "closed"
            if state == "half-open":
                # If any fail -> open again
                await self.redis.set(self.state_key, "open")
                await self.redis.set(self.opened_at_key, str(time.time()))
                circuit_breaker_trips.labels(provider=self.name).inc()
            elif state == "closed":
                failures = await self.redis.incr(self.failure_key)
                if failures >= self.failure_threshold:
                    # Open the circuit
                    await self.redis.set(self.state_key, "open")
                    await self.redis.set(self.opened_at_key, str(time.time()))
                    circuit_breaker_trips.labels(provider=self.name).inc()
                    active_circuit_breakers_open.inc()

        # We do not suppress exceptions
        return False
