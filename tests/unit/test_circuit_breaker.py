import pytest
import time
from unittest.mock import AsyncMock, patch

from backend.resilience.circuit_breaker import CircuitBreaker, CircuitOpenError

@pytest.fixture
def mock_redis():
    mock = AsyncMock()
    # By default, pretend the keys don't exist
    mock.get.return_value = None
    mock.incr.return_value = 1
    return mock

@pytest.fixture
def circuit_breaker(mock_redis):
    with patch("backend.resilience.circuit_breaker.get_redis_client", return_value=mock_redis):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=1, half_open_max_calls=2)
        yield cb

@pytest.mark.asyncio
async def test_closed_success(circuit_breaker, mock_redis):
    mock_redis.get.return_value = "closed"
    
    async with circuit_breaker:
        pass
    
    mock_redis.set.assert_called_with(circuit_breaker.failure_key, 0)

@pytest.mark.asyncio
async def test_closed_to_open(circuit_breaker, mock_redis):
    mock_redis.get.return_value = "closed"
    mock_redis.incr.return_value = 2 # Threshold reached
    
    try:
        async with circuit_breaker:
            raise ValueError("Some error")
    except ValueError:
        pass
        
    mock_redis.set.assert_any_call(circuit_breaker.state_key, "open")

@pytest.mark.asyncio
async def test_open_raises_error(circuit_breaker, mock_redis):
    mock_redis.get.side_effect = lambda k: "open" if "state" in k else str(time.time())
    
    with pytest.raises(CircuitOpenError):
        async with circuit_breaker:
            pass

@pytest.mark.asyncio
async def test_open_to_half_open(circuit_breaker, mock_redis):
    # Simulate opened 2 seconds ago, recovery timeout is 1
    mock_redis.get.side_effect = lambda k: "open" if "state" in k else str(time.time() - 2)
    
    async with circuit_breaker:
        pass # Success inside half-open
        
    mock_redis.set.assert_any_call(circuit_breaker.state_key, "half-open")

@pytest.mark.asyncio
async def test_half_open_to_closed(circuit_breaker, mock_redis):
    mock_redis.get.return_value = "half-open"
    mock_redis.incr.return_value = 1
    
    async with circuit_breaker:
        pass
        
    mock_redis.set.assert_any_call(circuit_breaker.state_key, "closed")

@pytest.mark.asyncio
async def test_half_open_to_open(circuit_breaker, mock_redis):
    mock_redis.get.return_value = "half-open"
    mock_redis.incr.return_value = 1
    
    try:
        async with circuit_breaker:
            raise ValueError("Another error")
    except ValueError:
        pass
        
    mock_redis.set.assert_any_call(circuit_breaker.state_key, "open")
