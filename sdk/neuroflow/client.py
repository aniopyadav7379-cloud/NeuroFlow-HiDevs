import asyncio
import json
import time
from pathlib import Path
from types import TracebackType
from typing import Any, AsyncGenerator, Dict, Optional, Type, Union

import httpx
from httpx_sse import aconnect_sse

from .exceptions import (
    IngestionFailedError,
    NeuroFlowAPIError,
    NeuroFlowTimeoutError,
)
from .models import Document, EvaluationResult, QueryResult

# Status codes the backend can return that represent a transient condition the
# caller should retry, rather than a permanent client error. 503 specifically
# matches backend.resilience.backpressure - ingest endpoints return 503 with a
# {"error": "ingestion_queue_full", "retry_after": N} body when the ingestion
# queue is too deep; 502/504 are typical upstream/gateway transients.
_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


class NeuroFlowClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = {"Authorization": f"Bearer {self.api_key}"}
        self.client = httpx.AsyncClient(headers=self.headers, timeout=timeout)

    async def __aenter__(self) -> "NeuroFlowClient":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.close()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self.base_url}{path}"
        max_retries = 5
        base_delay = 1.0

        for attempt in range(max_retries):
            response = await self.client.request(method, url, **kwargs)

            if response.status_code in _RETRYABLE_STATUS_CODES:
                if attempt == max_retries - 1:
                    raise NeuroFlowAPIError(
                        f"{method} {path} failed after {max_retries} attempts "
                        f"(last status {response.status_code})",
                        response=response,
                    )

                # Prefer the server's own guidance on how long to wait: the
                # Retry-After header (used by the 429 rate limiter,
                # backend/resilience/rate_limiter.py), then a "retry_after"
                # field in the JSON body (used by the 503 backpressure
                # response, backend/resilience/backpressure.py), then fall
                # back to exponential backoff.
                delay = self._retry_delay(response, base_delay, attempt)
                await asyncio.sleep(delay)
                continue

            if response.status_code >= 400:
                raise NeuroFlowAPIError(
                    f"{method} {path} returned {response.status_code}: {response.text}",
                    response=response,
                )
            return response

        raise NeuroFlowAPIError(f"Max retries exceeded for {method} {path}")

    @staticmethod
    def _retry_delay(response: httpx.Response, base_delay: float, attempt: int) -> float:
        retry_after_header = response.headers.get("Retry-After")
        if retry_after_header is not None:
            try:
                return float(retry_after_header)
            except ValueError:
                pass

        try:
            body = response.json()
            if isinstance(body, dict) and "retry_after" in body:
                return float(body["retry_after"])
        except (json.JSONDecodeError, ValueError):
            pass

        return float(base_delay * (2**attempt))

    async def ingest_file(
        self,
        file_path: Union[str, Path],
        pipeline_id: Optional[str] = None,
        poll_timeout: float = 300.0,
    ) -> Document:
        """Upload and ingest a file, then poll until ingestion completes.

        Raises NeuroFlowTimeoutError if the document has not reached a
        terminal status within poll_timeout seconds, and IngestionFailedError
        if the backend reports status="error".
        """
        path = Path(file_path)
        with open(path, "rb") as f:
            files = {"file": (path.name, f, "application/octet-stream")}
            data = {"pipeline_id": pipeline_id} if pipeline_id else {}
            response = await self._request("POST", "/ingest/file", files=files, data=data)

        doc_data = response.json()
        return await self._poll_ingestion(doc_data["document_id"], poll_timeout)

    async def ingest_url(
        self,
        url: str,
        pipeline_id: Optional[str] = None,
        poll_timeout: float = 300.0,
    ) -> Document:
        """Ingest a URL, then poll until ingestion completes.

        Raises NeuroFlowTimeoutError if the document has not reached a
        terminal status within poll_timeout seconds, and IngestionFailedError
        if the backend reports status="error".
        """
        data: Dict[str, Any] = {"url": url}
        if pipeline_id:
            data["pipeline_id"] = pipeline_id

        response = await self._request("POST", "/ingest/url", json=data)
        doc_data = response.json()
        return await self._poll_ingestion(doc_data["document_id"], poll_timeout)

    async def _poll_ingestion(self, document_id: str, poll_timeout: float) -> Document:
        """Polls GET /documents/{id} until ingestion is complete.

        NOTE: this previously had no timeout at all and could poll forever if
        a document never reached a terminal status (e.g. a worker outage).
        """
        deadline = time.monotonic() + poll_timeout
        while True:
            response = await self._request("GET", f"/documents/{document_id}")
            data = response.json()
            if data["status"] == "complete":
                return Document(document_id=document_id, **data)
            elif data["status"] == "error":
                raise IngestionFailedError(document_id, detail=data.get("metadata"))

            if time.monotonic() >= deadline:
                raise NeuroFlowTimeoutError(
                    f"Timed out after {poll_timeout}s waiting for document "
                    f"{document_id} to finish ingesting (last status: {data['status']!r})"
                )
            await asyncio.sleep(2.0)

    async def query(
        self, query: str, pipeline_id: str, stream: bool = False
    ) -> Union[QueryResult, AsyncGenerator[str, None]]:
        """Run a RAG query. If stream=True, returns an async generator of tokens."""
        payload = {"query": query, "pipeline_id": pipeline_id, "stream": stream}

        response = await self._request("POST", "/query", json=payload)
        data = response.json()

        if not stream:
            return QueryResult(**data)

        run_id = data["run_id"]

        async def stream_generator() -> AsyncGenerator[str, None]:
            url = f"{self.base_url}/query/{run_id}/stream"
            max_retries = 5
            base_delay = 1.0

            for attempt in range(max_retries):
                try:
                    async with aconnect_sse(self.client, "GET", url) as event_source:
                        async for event in event_source.aiter_sse():
                            if event.event == "message":
                                event_data = json.loads(event.data)
                                if event_data.get("type") == "token":
                                    yield event_data["delta"]
                                elif event_data.get("type") == "error":
                                    raise NeuroFlowAPIError(event_data["message"])
                                elif event_data.get("type") == "done":
                                    return
                    return
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429 and attempt < max_retries - 1:
                        delay = self._retry_delay(e.response, base_delay, attempt)
                        await asyncio.sleep(delay)
                        continue
                    raise NeuroFlowAPIError(
                        f"Streaming query failed: {e}", response=e.response
                    ) from e

        return stream_generator()

    async def get_evaluation(
        self, run_id: str, wait: bool = True, poll_timeout: float = 120.0
    ) -> EvaluationResult:
        """Get evaluation results for a query run.

        NOTE: this previously retried on 404 forever when wait=True. Added a
        poll_timeout so a run whose evaluation never lands (e.g. the
        evaluation queue is stalled) fails loudly instead of hanging.
        """
        deadline = time.monotonic() + poll_timeout
        while True:
            try:
                response = await self.client.get(
                    f"{self.base_url}/evaluations/{run_id}", headers=self.headers
                )
                if response.status_code == 404 and wait:
                    if time.monotonic() >= deadline:
                        raise NeuroFlowTimeoutError(
                            f"Timed out after {poll_timeout}s waiting for evaluation "
                            f"of run {run_id}"
                        )
                    await asyncio.sleep(5.0)
                    continue
                if response.status_code >= 400:
                    raise NeuroFlowAPIError(
                        f"GET /evaluations/{run_id} returned {response.status_code}: "
                        f"{response.text}",
                        response=response,
                    )
                return EvaluationResult(**response.json())
            except httpx.HTTPStatusError as e:
                raise NeuroFlowAPIError(str(e), response=e.response) from e

    async def list_pipelines(self) -> list[dict[str, Any]]:
        response = await self._request("GET", "/pipelines")
        result: list[dict[str, Any]] = response.json()
        return result

    async def create_pipeline(self, config: dict[str, Any]) -> dict[str, Any]:
        response = await self._request("POST", "/pipelines", json=config)
        result: dict[str, Any] = response.json()
        return result

    async def close(self) -> None:
        await self.client.aclose()
