# NeuroFlow

An async, production-oriented Retrieval-Augmented Generation (RAG) platform:
FastAPI backend, ARQ background worker, PostgreSQL + pgvector, Redis, a
Next.js dashboard, a Python SDK, and an LLM-as-judge evaluation pipeline -
built incrementally as a structured, multi-task engineering project.

> A previously-listed "Live API Production URL" pointing at Railway has been
> removed from this README - it could not be verified as reachable during
> this audit (this sandbox's network access doesn't permit checking it), so
> it isn't claimed here as working. If you have a live deployment, add it
> back once you've confirmed it's actually up.

## What it does

- **Ingest** PDFs, DOCX, images (OCR), CSVs, and URLs - extract, chunk,
  embed, and index into pgvector, with content-hash deduplication and
  async background processing via an ARQ worker.
- **Retrieve** with hybrid search: dense (embedding) + sparse (keyword)
  search fused with Reciprocal Rank Fusion, plus reranking.
- **Generate** streamed answers (SSE) via a provider-routing abstraction
  (`backend/providers/`) with circuit breakers and fallback between LLM
  providers, citation extraction, and think-tag parsing.
- **Evaluate** generation and retrieval quality with a genuine LLM-as-judge
  (`evaluation/judge.py`, `evaluation/metrics/`) - not a placeholder; see
  "Evaluation integrity" below for a real fabrication issue found and fixed
  during this audit.
- **Serve a Python SDK** (`sdk/`) wrapping ingestion, querying/streaming,
  evaluation polling, and pipeline management, with real retry/timeout
  handling matched to the backend's actual resilience behavior.

## Architecture

```
                    ┌─────────────┐
  Client / SDK ───▶ │   FastAPI   │──▶ PostgreSQL (+ pgvector)
                    │  (backend/) │──▶ Redis (queue, cache, rate limit,
                    └──────┬──────┘      circuit-breaker state)
                           │ enqueue (queue:ingest)
                           ▼
                    ┌─────────────┐
                    │ ARQ worker  │──▶ sandboxed sibling container
                    │(backend/    │     (untrusted file parsing)
                    │ worker.py)  │
                    └─────────────┘
```

Full subsystem-level design (ingestion/retrieval/generation/evaluation/
fine-tuning, with diagrams and ADRs) is in [`docs/architecture.md`](docs/architecture.md).
Operational details - real service ports, health-check shape, incident
playbooks - are in [`docs/runbook.md`](docs/runbook.md).

## Project structure

```
backend/       FastAPI app: API routes, auth, resilience (circuit breakers,
                rate limiting, backpressure), security, DB/Redis pooling
worker.py       ARQ background worker entrypoint (ingestion jobs, cron)
pipelines/      Ingestion, retrieval, and generation pipeline implementations
evaluation/     LLM-as-judge evaluation, retrieval MRR eval, hyperparameter
                search, fine-tuning hooks
frontend/       Next.js dashboard
sdk/            Python SDK (neuroflow package) + examples
infra/          Docker Compose (dev + prod), nginx, DB init SQL
docs/           Architecture, ADRs, API contracts, data models, runbook
tests/          Unit, integration, performance, benchmark tests
.github/        CI (test/lint/security/build), release, dependabot
```

## Setup

```bash
cp .env.example .env   # fill in required values - see .env.example
cd infra
docker compose up -d
docker compose logs -f api worker
```

Required env vars: `POSTGRES_PASSWORD`, `POSTGRES_URL`, `REDIS_PASSWORD`,
`REDIS_URL`, `OPENAI_API_KEY`, `MLFLOW_TRACKING_URI`, `JWT_SECRET_KEY`,
`PLUGIN_SECRETS_KEY`, `ENVIRONMENT`. `postgres`/`redis` are **not** exposed
to the host in the default compose file (internal-only) - see
`docs/runbook.md` for debugging access via `docker compose exec`.

**TLS for local HTTPS (production compose only):** `infra/nginx/certs/`
doesn't ship a committed certificate/key (see
`infra/nginx/certs/README.md` for why, and the one-line `openssl` command to
generate your own).

API docs (interactive): `http://localhost:8000/docs` once running.

## Python SDK

```bash
pip install -e ./sdk
```

```python
async with NeuroFlowClient(base_url, api_key) as client:
    doc = await client.ingest_file("report.pdf", pipeline_id=pipeline_id)
    result = await client.query("What does the report say?", pipeline_id=pipeline_id)
```

See [`sdk/README.md`](sdk/README.md) for the full guide (auth, streaming,
retries, error handling) and [`sdk/examples/quickstart.py`](sdk/examples/quickstart.py)
for a runnable end-to-end example.

## Testing

```bash
pytest tests/unit          # no live infra required
pytest tests/integration   # requires live Postgres/Redis (docker compose up)
ruff check .
mypy backend/ pipelines/ evaluation/ --ignore-missing-imports
```

As of this audit: **32 unit tests pass** with no live infrastructure
(`tests/unit`, one file excluded - `test_chunker.py` needs a one-time
tiktoken vocabulary download this sandbox's network doesn't allow, unrelated
to application code). Integration tests require a live Postgres/Redis and
were not run end-to-end here for the same reason - see
`docs/runbook.md`/the project retrospective for exactly what is and isn't
verified.

## Evaluation integrity

During this audit, three separate places in the evaluation pipeline were
found to be **fabricating** scores with `random.uniform()` instead of
calling the real LLM judge - including the production Redis-queue consumer
that populates the live evaluation dashboard, not just a test endpoint. All
three have been fixed to use the genuine per-metric LLM-as-judge
(`evaluation/judge.py`, `evaluation/metrics/`). Numbers already stored in
`evaluation/quality_baseline.json` / `quality_final.json` / etc. predate the
fix and should be treated as stale until those scripts are re-run against a
live DB + LLM provider. Full detail: [`evaluation/improvement_log.md`](evaluation/improvement_log.md).

## Known limitations

- No load-tested production deployment is claimed or verified here.
- Retrieval/generation quality metrics need to be regenerated post-fix (see
  above) before being cited anywhere as current numbers.
- OpenAPI documents `200`/`422` responses for most endpoints but not every
  `400`/`404`/`503` the code can actually return - a real documentation
  completeness gap, not fixed as part of this audit.
- `api`/`worker` mount the host Docker socket to sandbox untrusted file
  parsing in a sibling container - a deliberate, documented trade-off (see
  `docs/runbook.md` Section 6), not an oversight.
