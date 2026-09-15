from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

# Telemetry
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from backend.config import settings
from backend.db.health import check_mlflow, check_postgres, check_redis
from backend.db.migrations import run_migrations
from backend.db.pool import close_pool, create_pool
from backend.db.retention import start_retention_scheduler, stop_retention_scheduler

# Setup tracing
resource = Resource.create({"service.name": "neuroflow-api"})
provider = TracerProvider(resource=resource)
jaeger_endpoint = (
    "http://jaeger:4317" if settings.postgres_host == "postgres" else "http://localhost:4317"
)
try:
    exporter = OTLPSpanExporter(endpoint=jaeger_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
except Exception:
    pass

import asyncio  # noqa: E402

from backend.api.evaluations import process_evaluation_queue  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:  # noqa: ANN401
    # Startup
    await create_pool()
    
    if settings.env_prefix:
        from backend.db.pool import get_pool  # noqa: I001, PLC0415
        import os  # noqa: I001, PLC0415
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {settings.env_prefix}")
            q = f"SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = '{settings.env_prefix}' AND table_name = 'documents')"  # noqa: E501
            table_exists = await conn.fetchval(q)
            if not table_exists:
                schema_path = os.path.join(os.path.dirname(__file__), "../infra/init/001_schema.sql")  # noqa: ASYNC240, E501
                rls_path = os.path.join(os.path.dirname(__file__), "../infra/init/002_rls.sql")  # noqa: ASYNC240, E501
                if os.path.exists(schema_path):  # noqa: ASYNC240
                    with open(schema_path, encoding="utf-8") as f:  # noqa: ASYNC230
                        await conn.execute(f.read())
                if os.path.exists(rls_path):  # noqa: ASYNC240
                    with open(rls_path, encoding="utf-8") as f:  # noqa: ASYNC230
                        await conn.execute(f.read())
    
    await run_migrations()

    # Start background evaluation queue processor
    task = asyncio.create_task(process_evaluation_queue())
    
    # Start data retention scheduled jobs
    start_retention_scheduler()

    yield
    # Shutdown
    stop_retention_scheduler()
    task.cancel()
    await close_pool()


from fastapi import Depends  # noqa: E402

from backend.api import auth, compare, evaluations, finetune, ingest, pipelines, query  # noqa: E402
from backend.api.runs import router as runs_router  # noqa: E402
from backend.security.auth import get_current_user  # noqa: E402
from backend.security.middleware import SecurityHeadersMiddleware  # noqa: E402

app = FastAPI(title="NeuroFlow API", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)

# Auth router doesn't require authentication for /token
app.include_router(auth.router)

# All other routers require JWT auth
app.include_router(ingest.router, dependencies=[Depends(get_current_user)])
app.include_router(query.router, dependencies=[Depends(get_current_user)])
app.include_router(runs_router, dependencies=[Depends(get_current_user)])
app.include_router(pipelines.router, dependencies=[Depends(get_current_user)])
app.include_router(compare.router, dependencies=[Depends(get_current_user)])
app.include_router(finetune.router, dependencies=[Depends(get_current_user)])
app.include_router(evaluations.router, dependencies=[Depends(get_current_user)])

# Instrument the app
FastAPIInstrumentor.instrument_app(app)


@app.get(
    "/health",
    summary="System Health Check",
    description=(
        "Returns the current operational status of the API, PostgreSQL database, and Redis cache. "
        "Useful for Kubernetes liveness/readiness probes."
    ),
    response_description="A JSON object detailing the health status of all subsystems.",
    tags=["Admin"]
)
async def health_check() -> Any:  # noqa: ANN401
    pg_res = await check_postgres()
    redis_res = await check_redis()
    mlflow_res = await check_mlflow()

    try:
        import redis.asyncio as aioredis

        from backend.config import settings

        r = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
        )

        cb_status = {}
        for provider in ["openai", "anthropic"]:
            state = await r.get(f"circuit:{provider}:state") or "closed"
            cb: dict[str, Any] = {"state": state}
            if state == "open":
                cb["opened_at"] = await r.get(f"circuit:{provider}:opened_at")
            else:
                fails = await r.get(f"circuit:{provider}:failure_count")
                cb["failure_count"] = int(fails) if fails else 0
            cb_status[provider] = cb

        # NOTE: arq's enqueue_job() stores queued job ids in a Redis sorted set
        # (ZADD), not a list - LLEN against that key raises WRONGTYPE once any
        # real job has been enqueued, which silently zeroed out this whole
        # try block (caught by the except below) instead of reporting real
        # status. Use ZCARD, matching how the queue is actually populated.
        queue_depth = await r.zcard("queue:ingest")

        # arq does not maintain an "arq:workers" set in this version - that key
        # is never written by arq, so checking it always returned 0 workers
        # (and the old code masked that with a hardcoded "2" fallback below).
        # arq's real liveness signal is a per-queue health-check key with a TTL
        # that a running worker refreshes periodically (see arq.worker.Worker.
        # record_health). Treat its mere presence as "a worker is alive".
        health_check_key = "queue:ingest:health-check"
        worker_health_raw = await r.get(health_check_key)
        worker_count = 1 if worker_health_raw else 0
        await r.aclose()
    except Exception:
        cb_status = {}
        queue_depth = 0
        worker_count = 0

    is_critical = pg_res["status"] == "error" or redis_res["status"] == "error"
    is_degraded = any(c["state"] == "open" for c in cb_status.values())
    all_checks_pass = (
        pg_res["status"] == "ok" and redis_res["status"] == "ok" and mlflow_res["status"] == "ok"
    )

    if is_critical:
        status = "critical"
    elif is_degraded or not all_checks_pass:
        status = "degraded"
    else:
        status = "ok"

    return {
        "status": status,
        "checks": {
            "postgres": pg_res,
            "redis": redis_res,
            "mlflow": mlflow_res,
            "circuit_breakers": cb_status,
            "queue_depth": queue_depth,
            "worker_count": worker_count,
        },
    }


@app.get(
    "/metrics",
    summary="Prometheus Metrics",
    description=(
        "Exposes internal Prometheus metrics including request counts, error rates, "
        "and API latencies. Intended to be scraped by a Prometheus server."
    ),
    response_description="Plain text Prometheus metrics exposition format.",
    tags=["Admin"]
)
async def metrics() -> Any:  # noqa: ANN401
    # Prometheus text format
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
