# NeuroFlow Python SDK

An async Python client for the NeuroFlow RAG API (ingestion, retrieval,
generation, streaming, and evaluation).

## Installation

```bash
pip install -e ./sdk
```

Requires Python >= 3.9. Depends on `httpx`, `httpx-sse`, and `pydantic` (see
`sdk/pyproject.toml`).

## Configuration & authentication

The client needs the API's base URL and a Bearer token:

```python
from neuroflow import NeuroFlowClient

client = NeuroFlowClient(
    base_url="http://localhost:8000",  # or your deployment's URL
    api_key="your-token",              # sent as Authorization: Bearer <token>
    timeout=30.0,                      # per-request httpx timeout, in seconds
)
```

Tokens are issued by `POST /auth/token` (see the backend's `/docs` for that
endpoint's request/response shape - the SDK does not currently wrap it, so
fetch a token separately and pass it in here). Some endpoints require
specific scopes on the token - e.g. `POST /pipelines` requires `admin` scope.

## Client lifecycle

Prefer the async context manager, which closes the underlying `httpx.AsyncClient`
for you even if an exception is raised:

```python
async with NeuroFlowClient(base_url, api_key) as client:
    ...
```

Or manage it manually:

```python
client = NeuroFlowClient(base_url, api_key)
try:
    ...
finally:
    await client.close()
```

## Ingestion

```python
doc = await client.ingest_file("report.pdf", pipeline_id="<pipeline-uuid>")
# or:
doc = await client.ingest_url("https://example.com/article", pipeline_id="<pipeline-uuid>")

print(doc.document_id, doc.status, doc.chunk_count)
```

Both methods upload/submit the document, then **poll** `GET /documents/{id}`
internally until the backend reports `status == "complete"`. Pass
`poll_timeout` (seconds, default `300.0`) to bound how long that polling
runs - if the document hasn't finished by then, `NeuroFlowTimeoutError` is
raised instead of hanging indefinitely. If the backend reports
`status == "error"`, `IngestionFailedError` is raised.

## Querying

```python
result = await client.query("What does the report say about Q3 revenue?", pipeline_id=pipeline_id)
print(result.answer)
print(result.citations)
```

### Streaming

`query(..., stream=True)` is still a coroutine - it returns an async
generator once awaited, it is not itself an async generator:

```python
stream = await client.query(query, pipeline_id=pipeline_id, stream=True)
async for token in stream:
    print(token, end="", flush=True)
```

`async for token in client.query(..., stream=True)` (without the `await`)
will raise `TypeError: 'async for' requires an object with __aiter__ method,
got coroutine` - this is a genuine footgun in the current API shape, so it's
called out explicitly here and in `sdk/examples/quickstart.py`.

## Evaluations

```python
from neuroflow.exceptions import NeuroFlowTimeoutError

try:
    evaluation = await client.get_evaluation(result.run_id, wait=True, poll_timeout=120.0)
    print(evaluation.faithfulness, evaluation.overall_score)
except NeuroFlowTimeoutError:
    print("Evaluation hadn't landed within 120s - it may still be queued.")
```

With `wait=True` (the default), the client polls until an evaluation row
exists for the run or `poll_timeout` elapses. With `wait=False`, a 404
raises immediately instead of polling.

## Pipelines

```python
pipelines = await client.list_pipelines()

pipeline = await client.create_pipeline({
    "config": {
        "name": "my-pipeline",
        "description": "...",
        "ingestion": {},                         # all fields have defaults
        "retrieval": {},                         # all fields have defaults
        "generation": {"model_routing": {}},     # model_routing's fields all have defaults
        "evaluation": {},                        # all fields have defaults
    }
})
```

`POST /pipelines` requires the request body's `config` key with all four
sub-sections present (`backend/models/pipeline.py` uses `extra="forbid"`, so
no other shape validates), and requires an API key with `admin` scope.

## Errors, retries, and timeouts

All SDK-raised errors derive from `neuroflow.NeuroFlowError`:

| Exception | Raised when |
|---|---|
| `NeuroFlowAPIError` | The backend returned a non-2xx response that wasn't retried away (`.status_code` and `.response` are available) |
| `NeuroFlowTimeoutError` | A client-side polling loop (ingestion or evaluation) exceeded its `poll_timeout` |
| `IngestionFailedError` | The backend reported `status="error"` for a document (`.document_id`, `.detail`) |

Requests are automatically retried (up to 5 attempts, exponential backoff by
default) on:
- `429 Too Many Requests` - the backend's rate limiter
  (`backend/resilience/rate_limiter.py`) sets a `Retry-After` header, which
  the SDK reads and waits for exactly, rather than guessing.
- `502` / `503` / `504` - transient upstream failures, including the
  ingestion backpressure response (`backend/resilience/backpressure.py`),
  which returns `503` with a JSON body containing `retry_after` (seconds);
  the SDK reads that field when present.

Any other 4xx/5xx status raises `NeuroFlowAPIError` immediately (no retry) -
these are treated as permanent failures (bad request, not found, etc.).

## Troubleshooting

- **`NeuroFlowAPIError` with `status_code == 401`** - check your API token;
  see `backend/security/auth.py`.
- **`NeuroFlowAPIError` with `status_code == 403`** - the token doesn't have
  the required scope for that endpoint (e.g. `admin` for `POST /pipelines`).
- **`NeuroFlowTimeoutError` from `ingest_file`/`ingest_url`** - either raise
  `poll_timeout`, or check the worker: ingestion jobs are processed by the
  ARQ worker consuming `queue:ingest` (`backend/worker.py`). If the worker
  isn't running, jobs will queue but never complete - see `docs/runbook.md`
  for worker troubleshooting.
- **`NeuroFlowTimeoutError` from `get_evaluation`** - the evaluation queue
  consumer (`backend/api/evaluations.py::process_evaluation_queue`) may be
  behind or the LLM provider it calls may be unavailable; check backend logs.
- **Connection refused** - confirm `base_url` points at a running instance
  (`docker compose up`, see `docs/runbook.md`) and that you're using the
  host-mapped port, not the container-internal one.

## API reference

The backend exposes a full OpenAPI schema at `/openapi.json` (interactive
docs at `/docs`) once running - that is the source of truth for request/
response shapes; this SDK wraps a subset of it (ingestion, querying,
streaming, evaluations, and basic pipeline management).
