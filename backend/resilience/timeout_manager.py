"""
Explicit, context-appropriate timeouts for every external call, plus a
Redis counter (`timeouts:{task_type}`) so timeout frequency is visible in
GET /health and dashboards — a task type that's timing out a lot is a
signal worth seeing before it becomes an outage.
"""
import asyncio
import logging

logger = logging.getLogger("neuroflow.resilience.timeout_manager")

DEFAULT_TIMEOUTS = {
    "embedding": 10,
    "chat_completion": 60,
    "reranking": 15,
    "evaluation": 120,  # evaluation is slower (multiple LLM calls)
    "file_extraction": 30,
    "url_fetch": 15,
}
FALLBACK_TIMEOUT = 30  # used for any task_type not in the table above


class OperationTimeoutError(TimeoutError):
    def __init__(self, task_type: str, timeout: float):
        super().__init__(f"{task_type} timed out after {timeout}s")
        self.task_type = task_type
        self.timeout = timeout


class TimeoutManager:
    def __init__(self, redis_client, timeouts: dict[str, float] | None = None):
        self.redis = redis_client
        self.timeouts = timeouts or DEFAULT_TIMEOUTS

    def get_timeout(self, task_type: str) -> float:
        return self.timeouts.get(task_type, FALLBACK_TIMEOUT)

    async def run(self, task_type: str, coro):
        """Runs `coro` under asyncio.wait_for with the timeout for
        `task_type`. On timeout: logs it, increments timeouts:{task_type}
        in Redis, and raises OperationTimeoutError (a TimeoutError
        subclass) so it propagates to the caller exactly as the task
        spec asks — callers that want fallback behavior can catch it
        like any other TimeoutError."""
        timeout = self.get_timeout(task_type)
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("timeout on task_type=%s after %ss", task_type, timeout)
            if self.redis is not None:
                try:
                    await self.redis.incr(f"timeouts:{task_type}")
                except Exception:
                    logger.exception("failed to increment timeouts:%s counter (non-fatal)", task_type)
            raise OperationTimeoutError(task_type, timeout) from None

    async def get_all_counters(self) -> dict[str, int]:
        counters = {}
        for task_type in self.timeouts:
            raw = await self.redis.get(f"timeouts:{task_type}")
            counters[task_type] = int(raw) if raw else 0
        return counters
