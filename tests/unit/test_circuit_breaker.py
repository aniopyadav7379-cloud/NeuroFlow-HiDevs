import asyncio
import sys
import time
sys.path.insert(0, ".")
import pytest
from backend.resilience.circuit_breaker import CircuitBreaker, CircuitOpenError

class FakeRedis:
    def __init__(self):
        self.store = {}
        self.lock = asyncio.Lock()
    async def get(self, key): return self.store.get(key)
    async def set(self, key, val): self.store[key] = val
    async def incr(self, key):
        async with self.lock:
            self.store[key] = int(self.store.get(key, 0)) + 1
            return self.store[key]
    async def delete(self, key): self.store.pop(key, None)

@pytest.mark.asyncio
async def test_closed_state_allows_calls():
    cb = CircuitBreaker("t1", FakeRedis())
    async with cb:
        pass
    assert (await cb.get_status())["state"] == "closed"

@pytest.mark.asyncio
async def test_opens_after_failure_threshold():
    cb = CircuitBreaker("t2", FakeRedis(), failure_threshold=3)
    for _ in range(3):
        try:
            async with cb:
                raise RuntimeError("boom")
        except RuntimeError:
            pass
    assert (await cb.get_status())["state"] == "open"

@pytest.mark.asyncio
async def test_open_circuit_rejects_immediately():
    cb = CircuitBreaker("t3", FakeRedis(), failure_threshold=1)
    try:
        async with cb:
            raise RuntimeError()
    except RuntimeError:
        pass
    with pytest.raises(CircuitOpenError):
        async with cb:
            pass

@pytest.mark.asyncio
async def test_half_open_admits_exactly_max_calls_concurrently():
    r = FakeRedis()
    cb = CircuitBreaker("t4", r, failure_threshold=1, recovery_timeout=60, half_open_max_calls=2)
    await cb._open()
    r.store[cb._key("opened_at")] = time.time() - 61
    admitted = []
    async def make_call():
        try:
            async with cb:
                admitted.append(1)
                await asyncio.sleep(0.02)
        except CircuitOpenError:
            pass
    await asyncio.gather(*(make_call() for _ in range(5)))
    assert len(admitted) == 2

@pytest.mark.asyncio
async def test_half_open_success_closes_circuit():
    r = FakeRedis()
    cb = CircuitBreaker("t5", r, failure_threshold=1, recovery_timeout=60)
    await cb._open()
    r.store[cb._key("opened_at")] = time.time() - 61
    async with cb:
        pass
    assert (await cb.get_status())["state"] == "closed"

@pytest.mark.asyncio
async def test_half_open_failure_reopens_circuit():
    r = FakeRedis()
    cb = CircuitBreaker("t6", r, failure_threshold=1, recovery_timeout=60)
    await cb._open()
    r.store[cb._key("opened_at")] = time.time() - 61
    try:
        async with cb:
            raise RuntimeError()
    except RuntimeError:
        pass
    assert (await cb.get_status())["state"] == "open"
