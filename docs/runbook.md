# NeuroFlow Architecture & Operations Runbook

This runbook documents the actual NeuroFlow deployment (`infra/docker-compose.yml`) and
gives on-call engineers verified troubleshooting steps. Every command and path below was
checked against the real code in this repository as of this audit; where something
couldn't be verified against a live deployment, it's marked as such rather than assumed.

## 1. Architecture

Services (`infra/docker-compose.yml`):

| Service | Image / build | Host port | Purpose |
|---|---|---|---|
| `api` | `backend/Dockerfile` | `8000` | FastAPI app (`backend/main.py`), serves `/ingest`, `/query`, `/pipelines`, `/evaluations`, `/health`, `/metrics`, `/docs` |
| `worker` | same image as `api`, cmd `arq backend.worker.WorkerSettings` | *(none - internal only)* | ARQ background worker: processes ingestion jobs and the `poll_finetune_jobs` cron |
| `postgres` | `pgvector/pgvector:pg16` | *(none - internal only)* | Primary datastore + vector search (pgvector) |
| `redis` | `redis:7-alpine` | *(none - internal only)* | Job queue (ARQ), caching, rate limiting, circuit-breaker state |
| `mlflow` | `Dockerfile.mlflow` | `5000` | Experiment tracking for generation eval / hyperparameter search / fine-tuning |
| `jaeger` | `jaegertracing/all-in-one` | `16686` (UI), `4317` (OTLP) | Distributed tracing |
| `prometheus` | `prom/prometheus` | `9090` | Metrics scraping (`/metrics` on `api`) |
| `grafana` | `grafana/grafana` | `3000` | Dashboards over Prometheus |

**Important:** `postgres` and `redis` do **not** publish host ports in
`infra/docker-compose.yml` - they're only reachable from other containers on the compose
network (e.g. `postgres:5432`, `redis:6379` from inside `api`/`worker`), not from the host
machine. If you need to connect from the host for debugging, use `docker compose exec
postgres psql ...` / `docker compose exec redis redis-cli ...` rather than assuming
`localhost:5432`/`localhost:6379` work.

**Two different "workers," don't confuse them:** the `api` container runs `uvicorn
backend.main:app ... --workers 4` (4 uvicorn *processes* serving HTTP), while the
`worker` container runs the separate ARQ *background job worker*. "Restart the worker"
in an ingestion incident means the `worker` service, not `api`.

### Ingestion queue naming

Ingestion jobs are enqueued to Redis key `queue:ingest` (a Redis **sorted set**, via
ARQ's `enqueue_job(..., _queue_name="queue:ingest")` in `backend/api/ingest.py`), and
`backend/worker.py`'s `WorkerSettings.queue_name` is set to `"queue:ingest"` to match.
*(This queue-name match was a real bug found and fixed during this audit - the worker
previously defaulted to ARQ's own `"arq:queue"` and never consumed `"queue:ingest"` at
all, so ingestion jobs would queue but never process. If you're running an older build,
confirm `backend/worker.py` actually sets `queue_name = "queue:ingest"` before relying on
any of the ingestion troubleshooting below.)*

## 2. Startup / shutdown

```bash
# from infra/
cp ../.env.example ../.env   # fill in required values, see below
docker compose up -d
docker compose logs -f api worker   # watch startup
docker compose down                 # stop (add -v to also drop volumes/data)
```

Required environment variables (`.env.example`): `POSTGRES_PASSWORD`, `POSTGRES_URL`,
`REDIS_PASSWORD`, `REDIS_URL`, `OPENAI_API_KEY`, `MLFLOW_TRACKING_URI`,
`JWT_SECRET_KEY`, `PLUGIN_SECRETS_KEY`, `ENVIRONMENT`. Optional: `ANTHROPIC_API_KEY`,
`OTEL_EXPORTER_OTLP_ENDPOINT`, `SENTRY_DSN`, `LOG_LEVEL`.

On `api` startup (`backend/main.py` lifespan), the app: creates its Postgres pool,
ensures the configured schema exists, and starts `process_evaluation_queue()` as a
background task (real per-metric LLM judging of queued runs - see Section 5). On
shutdown it cancels that task and closes the pool.

## 3. Health checks

`GET /health` returns:

```json
{
  "status": "ok | degraded | critical",
  "checks": {
    "postgres": {...}, "redis": {...}, "mlflow": {...},
    "circuit_breakers": {"openai": {"state": "closed|open|half-open", ...}, "anthropic": {...}},
    "queue_depth": <int>,
    "worker_count": <0 or 1>
  }
}
```

- `status: "critical"` - Postgres or Redis check failed.
- `status: "degraded"` - a circuit breaker is open, or Postgres/Redis/MLflow isn't fully
  healthy.
- `queue_depth` - real `ZCARD` of `queue:ingest` (fixed this audit pass; previously used
  `LLEN` against what is actually a sorted-set key, which raises `WRONGTYPE` in real
  Redis).
- `worker_count` - `1` if ARQ's own health-check key
  (`queue:ingest:health-check`, refreshed periodically by a running worker - see
  `arq.worker.Worker.record_health`) exists, else `0`. This is a liveness signal, not an
  exact process count - do not read it as "N workers are running."
  **NOT VERIFIED end-to-end in this audit** (no live Redis/worker in this sandbox);
  correct per ARQ 0.26.0's source and confirmed via `pytest` that the worker fixture now
  starts without error, but the health value itself hasn't been observed against a real
  running worker.

The `worker_count`/`queue_depth` logic used to silently return `0`/`{}` on *any*
exception (including the `WRONGTYPE` error above), which masked real circuit-breaker
state along with it. That's fixed, but keep in mind: if `/health`'s `checks` block ever
comes back mostly empty again, check `api` logs for a new exception in that block rather
than assuming everything is fine.

## 4. Incident playbooks

### Incident 1 - High query latency (P95 > 10s)

**Check:** Jaeger (`:16686`) traces for `POST /query` - is time in the retrieval span or
the generation/LLM span? `SELECT * FROM pg_stat_statements ORDER BY total_exec_time DESC
LIMIT 5;` for slow queries. Redis memory/eviction stats for cache thrashing.

**Remediate:** add missing indexes based on `pg_stat_statements`; scale `api` replicas if
CPU-bound; investigate LLM provider latency directly if the generation span dominates.

### Incident 2 - Evaluation scores degrading

**Check:** which pipeline/metric is dropping (MLflow / Prometheus `eval_overall`,
`eval_faithfulness`). Recent ingestion quality. Recent fine-tuning model swaps in MLflow.

**Note:** evaluation scores are produced by `EvaluationJudge.evaluate_run()`
(`evaluation/judge.py`), invoked from the real production queue consumer
(`process_evaluation_queue` in `backend/api/evaluations.py`) - this is a genuine
LLM-as-judge path, not a placeholder, as of this audit. If you're troubleshooting a
build from before this fix, check whether that function still uses `random.uniform()`
before trusting any dashboard number it produced.

**Remediate:** revert to a known-good fine-tuned model via MLflow if a recent swap is the
cause; inspect/clean recently ingested documents if data quality is the cause.

### Incident 3 - LLM provider circuit breaker open

**Symptoms:** requests failing fast with 503s instead of waiting on a slow/down provider.

**Check:** `GET /health` → `checks.circuit_breakers.<provider>.state == "open"`. Check the
provider's own status page.

**Remediate:** Circuit breakers (`backend/resilience/circuit_breaker.py`) auto-recover -
by default (`recovery_timeout=60`), the breaker moves to `half-open` and allows a limited
number of trial calls (`half_open_max_calls=3`) 60 seconds after it opened; it closes
again on the first success. There is **no manual-reset API endpoint** in this codebase
(an earlier version of this runbook referenced `POST /admin/circuit-breaker/reset`, which
does not exist anywhere in the code - do not rely on it during an incident). If you need
to force-close a breaker before the timeout (e.g. you've confirmed the provider is back
and don't want to wait), do it directly in Redis:
```bash
docker compose exec redis redis-cli -a "$REDIS_PASSWORD" DEL \
  circuit:openai:state circuit:openai:opened_at circuit:openai:failure_count
```
(substitute `anthropic` as needed). This is a direct state mutation, not an officially
supported operation - use with care and confirm the provider is actually healthy first.

### Incident 4 - Ingestion queue depth rising / documents stuck in `queued`

**Check:** `GET /health` → `checks.queue_depth`. `docker compose logs worker` for
unhandled exceptions/OOM. Confirm the worker is actually consuming `queue:ingest` (see
Section 1's queue-naming note - a worker listening on the wrong queue name will look
"idle" while the queue grows, with no errors logged at all).

**Remediate:** `docker compose restart worker` for a stuck/deadlocked process. For a
single poison-pill job repeatedly crashing the worker, identify and remove it from Redis
directly (`ZREM queue:ingest <job_id>` - the job ID isn't surfaced in the API today, so
this generally requires correlating worker logs with Redis).

### Incident 5 - Database disk usage > 80%

**Check:** which table is growing fastest - usually `evaluations` or `pipeline_runs`.
Confirm the daily retention job is running (`backend/db/retention.py`,
`start_retention_scheduler()`, scheduled via APScheduler cron at **03:00** daily - look
for its "Data retention cleanup completed successfully" log line). It deletes:
`pipeline_runs` older than 90 days with no evaluation and not flagged,
`evaluations` older than 180 days, and `chunks` belonging to `documents` with
`status='archived'`.

**Remediate:** run `run_data_retention_policy()` manually (e.g. via a one-off `python -c
"import asyncio; from backend.db.retention import run_data_retention_policy; ..."`
invocation inside the `api`/`worker` container - needs the DB pool initialized first) if
disk pressure can't wait for 03:00. `VACUUM FULL` during a maintenance window if bloat
(not just row count) is the issue.

## 5. Evaluation status (Task 18 integrity note)

As of this audit, three real LLM-as-judge fabrication issues were found and fixed:
`process_evaluation_queue` (production dashboard scores), `run_variant_eval` (A/B prompt
comparison), and `run_hyperparameter_search` (retrieval MRR). See
`evaluation/improvement_log.md` for full detail. Numbers already stored in
`evaluation/quality_baseline.json`, `evaluation/quality_final.json`, and
`evaluation/best_retrieval_config.json` predate the fix and are **UNVERIFIED / STALE**
until those scripts are re-run against a live DB + LLM provider. Do not cite them as
current quality metrics until they have been regenerated.

## 6. Security notes

- Bearer tokens (`backend/security/auth.py`), scoped (e.g. `admin` required for
  `POST /pipelines`).
- `bleach`-based sanitization on user-supplied text (`backend/security/prompt_injection.py`)
  plus pattern-based prompt-injection scanning.
- No standalone `LICENSE` file exists in this repository, and none was added during this
  audit.
- `postgres`/`redis` are not exposed to the host by the default compose file (see
  Section 1) - don't add host port mappings for them without a specific reason.
- `api`/`worker` mount the host's Docker socket (`/var/run/docker.sock`) so
  `pipelines/ingestion/pipeline.py` can spawn a sandboxed sibling container
  (`network_mode=none`, 256MB limit) to parse untrusted uploads in isolation.
  This is intentional, but worth knowing: Docker-socket access is
  root-equivalent on the host, so it moves the trust boundary rather than
  eliminating it - if `api`/`worker` is ever compromised through some other
  vector, socket access is already available. No change made to this during
  the audit; flagging it for awareness.
- **`infra/nginx/certs/dev.key` (a private key) was previously committed to
  this repository.** It has been removed from the working tree, `*.key` and
  `infra/nginx/certs/*.crt` are now gitignored, and
  `infra/nginx/certs/README.md` documents the exact `openssl` command to
  regenerate an equivalent local dev cert (verified to work). **This does not
  remove the key from git history** - anyone with repo access can still
  retrieve it from prior commits. If it was ever exposed outside this
  environment, rotate it; a full history rewrite (`git filter-repo`/BFG) is a
  separate, deliberate decision left to whoever owns this repo's remotes, not
  performed as part of this change (per the git restrictions in effect during
  this whole audit: no history rewrites, no force-pushes). Production
  deployments must supply a real CA-issued certificate at the same mount
  point rather than reusing any dev cert - see the README above.

## 7. What's NOT verified in this runbook

This runbook was written and cross-checked against the source code, but this audit
environment had no live Postgres, Redis, or LLM provider access. Anything above that
describes *expected* behavior based on reading the code (circuit-breaker recovery timing,
`/health` field values under real load, retention job execution) should be confirmed
against your actual deployment's logs/metrics the first time you rely on it during a real
incident.
