"""Integration tests for the resilience layer (Task 40) — circuit
breaker and rate limiting, against a running instance."""
import asyncio
import os
import time

import pytest

pytestmark = pytest.mark.asyncio

PIPELINE_ID = os.environ.get("NEUROFLOW_TEST_PIPELINE_ID", "")
requires_pipeline = pytest.mark.skipif(not PIPELINE_ID, reason="NEUROFLOW_TEST_PIPELINE_ID not set")


@pytest.mark.skip(
    reason="Test 3 (circuit breaker) requires mocking the LLM provider to return 500s "
    "from OUTSIDE the running instance (e.g. a mock OpenAI-compatible server the test "
    "instance is configured to hit via OPENAI_BASE_URL) — there's no in-process way to "
    "force backend/providers/openai_provider.py to fail from an external pytest process "
    "hitting the real HTTP API. Requires standing up infra/docker-compose.yml with "
    "OPENAI_BASE_URL pointed at a mock server (e.g. WireMock/httpbin returning 500s) "
    "before this test can run for real."
)
async def test_circuit_breaker_opens_and_recovers(client, auth_headers):
    for _ in range(5):
        resp = await client.post(
            "/query", json={"pipeline_id": PIPELINE_ID, "query": "test", "stream": False}, headers=auth_headers
        )
        assert resp.status_code >= 500

    health = await client.get("/health")
    assert health.json()["status"] == "degraded"
    assert any(cb["state"] == "open" for cb in health.json()["checks"]["circuit_breakers"].values())

    await asyncio.sleep(61)  # default recovery_timeout

    health2 = await client.get("/health")
    states = {name: cb["state"] for name, cb in health2.json()["checks"]["circuit_breakers"].items()}
    assert "half_open" in states.values() or "closed" in states.values()


@requires_pipeline
async def test_rate_limiting_returns_429(client, auth_headers):
    """Test 4: /query is limited to 60 req/min per IP — request 61+
    should get 429 with Retry-After."""
    responses = []
    for _ in range(70):
        resp = await client.post(
            "/query", json={"pipeline_id": PIPELINE_ID, "query": "rate limit probe", "stream": False},
            headers=auth_headers,
        )
        responses.append(resp)

    too_many = [r for r in responses if r.status_code == 429]
    assert len(too_many) >= 10, f"expected requests 61-70 to be rate limited, got {len(too_many)} 429s"
    assert "retry-after" in {h.lower() for h in too_many[0].headers}
