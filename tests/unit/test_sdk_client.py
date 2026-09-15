"""Unit tests for the neuroflow SDK client's retry/timeout behavior.

These target the real gaps found during the Phase 12 SDK audit:
- Retry-After header / retry_after body field being respected instead of a
  fixed exponential backoff.
- Polling timeouts on ingestion and evaluation, which previously could hang
  forever.
No network or live backend is required - httpx.Response objects are built
directly in-memory.
"""

import asyncio

import httpx
import pytest

from neuroflow.client import NeuroFlowClient
from neuroflow.exceptions import IngestionFailedError, NeuroFlowTimeoutError


def _response(status_code: int, json_body=None, headers=None) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=json_body if json_body is not None else {},
        headers=headers or {},
        request=httpx.Request("GET", "http://testserver/x"),
    )


class TestRetryDelay:
    def test_prefers_retry_after_header(self):
        resp = _response(429, headers={"Retry-After": "7"})
        delay = NeuroFlowClient._retry_delay(resp, base_delay=1.0, attempt=0)
        assert delay == 7.0

    def test_falls_back_to_retry_after_body_field(self):
        # Matches backend.resilience.backpressure's 503 response shape.
        resp = _response(503, json_body={"error": "ingestion_queue_full", "retry_after": 12})
        delay = NeuroFlowClient._retry_delay(resp, base_delay=1.0, attempt=0)
        assert delay == 12.0

    def test_falls_back_to_exponential_backoff(self):
        resp = _response(503, json_body={})
        delay = NeuroFlowClient._retry_delay(resp, base_delay=1.0, attempt=3)
        assert delay == 8.0  # 1.0 * 2**3

    def test_malformed_retry_after_header_falls_through(self):
        resp = _response(429, headers={"Retry-After": "not-a-number"})
        delay = NeuroFlowClient._retry_delay(resp, base_delay=1.0, attempt=1)
        assert delay == 2.0  # 1.0 * 2**1


class TestPollingTimeouts:
    @pytest.mark.asyncio
    async def test_poll_ingestion_times_out(self, monkeypatch):
        client = NeuroFlowClient("http://testserver", "key")

        async def fake_request(method, path, **kwargs):
            return _response(200, json_body={"status": "processing", "chunk_count": None})

        monkeypatch.setattr(client, "_request", fake_request)

        with pytest.raises(NeuroFlowTimeoutError):
            await client._poll_ingestion("doc-1", poll_timeout=0.01)

        await client.close()

    @pytest.mark.asyncio
    async def test_poll_ingestion_raises_on_error_status(self, monkeypatch):
        client = NeuroFlowClient("http://testserver", "key")

        async def fake_request(method, path, **kwargs):
            return _response(200, json_body={"status": "error", "metadata": {"reason": "bad pdf"}})

        monkeypatch.setattr(client, "_request", fake_request)

        with pytest.raises(IngestionFailedError):
            await client._poll_ingestion("doc-1", poll_timeout=10)

        await client.close()

    @pytest.mark.asyncio
    async def test_poll_ingestion_returns_on_complete(self, monkeypatch):
        client = NeuroFlowClient("http://testserver", "key")

        async def fake_request(method, path, **kwargs):
            return _response(
                200,
                json_body={"status": "complete", "chunk_count": 5, "metadata": {}},
            )

        monkeypatch.setattr(client, "_request", fake_request)

        doc = await client._poll_ingestion("doc-1", poll_timeout=10)
        assert doc.status == "complete"
        assert doc.chunk_count == 5

        await client.close()


class TestContextManager:
    @pytest.mark.asyncio
    async def test_async_context_manager_closes_client(self):
        async with NeuroFlowClient("http://testserver", "key") as client:
            assert client.client.is_closed is False
        assert client.client.is_closed is True
