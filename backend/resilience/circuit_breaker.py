"""
Circuit breaker pattern for external provider calls. State lives in
Redis (not in-process memory) specifically so it persists across API
restarts and is shared across every worker/API instance — one instance
tripping the breaker on repeated OpenAI failures immediately protects
every other instance too, instead of each process learning the hard way.
"""
import logging
import time
from enum import Enum

from backend.providers.base import RetryableProviderError

logger = logging.getLogger("neuroflow.resilience.circuit_breaker")

DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_RECOVERY_TIMEOUT = 60
DEFAULT_HALF_OPEN_MAX_CALLS = 3


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RetryableProviderError):
    """Raised when a call is rejected because the circuit is open (or
    half-open and already at its trial-call limit). Subclasses
    RetryableProviderError so FallbackChain (backend/providers/client.py)
    already knows how to fail over to the next provider on this without
    any changes there — a tripped breaker for one provider is exactly the
    kind of thing a fallback chain exists to route around."""


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        redis_client,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        recovery_timeout: int = DEFAULT_RECOVERY_TIMEOUT,
        half_open_max_calls: int = DEFAULT_HALF_OPEN_MAX_CALLS,
    ):
        self.name = name
        self.redis = redis_client
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

    def _key(self, suffix: str) -> str:
        return f"circuit:{self.name}:{suffix}"

    async def _read_state(self) -> tuple[str, int, float | None]:
        state = await self.redis.get(self._key("state"))
        failure_count = await self.redis.get(self._key("failure_count"))
        opened_at = await self.redis.get(self._key("opened_at"))
        return (
            state or CircuitState.CLOSED.value,
            int(failure_count) if failure_count else 0,
            float(opened_at) if opened_at else None,
        )

    async def get_status(self) -> dict:
        state, failure_count, opened_at = await self._read_state()
        return {
            "state": state,
            "failure_count": failure_count,
            "opened_at": opened_at,
        }

    async def _open(self) -> None:
        await self.redis.set(self._key("state"), CircuitState.OPEN.value)
        await self.redis.set(self._key("opened_at"), time.time())
        await self.redis.delete(self._key("half_open_calls"))
        logger.warning("circuit '%s' OPENED after reaching failure_threshold=%d", self.name, self.failure_threshold)

    async def _close(self) -> None:
        await self.redis.set(self._key("state"), CircuitState.CLOSED.value)
        await self.redis.set(self._key("failure_count"), 0)
        await self.redis.delete(self._key("opened_at"))
        await self.redis.delete(self._key("half_open_calls"))
        logger.info("circuit '%s' CLOSED (recovered)", self.name)

    async def _transition_to_half_open(self) -> None:
        await self.redis.set(self._key("state"), CircuitState.HALF_OPEN.value)
        await self.redis.delete(self._key("half_open_calls"))
        logger.info("circuit '%s' -> HALF_OPEN (recovery_timeout elapsed, testing)", self.name)

    async def _before_call(self) -> None:
        state, _failure_count, opened_at = await self._read_state()

        if state == CircuitState.OPEN.value:
            if opened_at is not None and (time.time() - opened_at) >= self.recovery_timeout:
                await self._transition_to_half_open()
                state = CircuitState.HALF_OPEN.value
            else:
                raise CircuitOpenError(f"circuit '{self.name}' is open")

        if state == CircuitState.HALF_OPEN.value:
            # Atomically admit at most half_open_max_calls trial calls —
            # INCR returns the post-increment count, so the Nth caller to
            # reach this sees exactly N, letting the first
            # half_open_max_calls through and rejecting the rest.
            admitted = await self.redis.incr(self._key("half_open_calls"))
            if admitted > self.half_open_max_calls:
                raise CircuitOpenError(f"circuit '{self.name}' is half-open and at its trial-call limit")

    async def _on_success(self) -> None:
        state, _, _ = await self._read_state()
        if state == CircuitState.HALF_OPEN.value:
            await self._close()
        elif state == CircuitState.OPEN.value:
            # shouldn't normally happen (a call that got in must have seen
            # half-open), but never leave a stray failure_count around
            await self.redis.set(self._key("failure_count"), 0)
        else:
            await self.redis.set(self._key("failure_count"), 0)

    async def _on_failure(self) -> None:
        state, _, _ = await self._read_state()
        if state == CircuitState.HALF_OPEN.value:
            # Any failure during the trial period re-opens immediately —
            # per spec, doesn't wait for failure_threshold again.
            await self._open()
            return

        new_count = await self.redis.incr(self._key("failure_count"))
        if new_count >= self.failure_threshold:
            await self._open()

    async def __aenter__(self) -> "CircuitBreaker":
        await self._before_call()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            await self._on_success()
        elif issubclass(exc_type, CircuitOpenError):
            pass  # our own rejection isn't a call failure, don't double-count it
        else:
            await self._on_failure()
        return False  # never suppress the exception


_breakers: dict[str, CircuitBreaker] = {}


def circuit_breaker(name: str, redis_client, **kwargs) -> CircuitBreaker:
    """Returns a process-local CircuitBreaker instance for `name`,
    reusing one across calls so config (thresholds) stays consistent —
    the actual open/closed STATE lives in Redis regardless, so this
    caching is purely to avoid re-constructing a trivial object, not a
    correctness requirement."""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name, redis_client, **kwargs)
    return _breakers[name]
