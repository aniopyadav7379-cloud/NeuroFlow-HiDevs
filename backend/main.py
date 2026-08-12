"""
NeuroFlow API — async FastAPI entrypoint.

Startup/shutdown is managed entirely through the `lifespan` context manager
(the modern FastAPI pattern) — no @app.on_event("startup"/"shutdown"),
which is deprecated. Connections created here (Postgres pool, Redis client)
are attached to app.state and torn down in the same function.
"""
import logging
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import Depends, FastAPI, Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from backend.config import get_settings
from backend.db.health import check_mlflow_timed, check_postgres_timed, check_redis_timed
from backend.resilience.backpressure import get_queue_depth
from backend.resilience.circuit_breaker import circuit_breaker
from backend.resilience.worker_heartbeat import get_worker_count
from backend.db.migrations import ensure_schema
from backend.db.pool import close_pool, create_pool
from backend.providers.client import build_client
from backend.security.auth import get_current_user
from backend.security.headers_middleware import SecurityHeadersMiddleware
from backend.api import auth as auth_api
from backend.api import chunks as chunks_api
from backend.api import compare as compare_api
from backend.api import evaluations as evaluations_api
from backend.api import finetune as finetune_api
from backend.api import ingest as ingest_api
from backend.api import pipelines as pipelines_api
from backend.api import query as query_api
from backend.api import runs as runs_api
from pipelines.ingestion.queue import create_arq_pool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("neuroflow.api")


def _setup_tracing(settings) -> None:
    if not settings.otel_traces_enabled:
        return
    resource = Resource(attributes={SERVICE_NAME: settings.otel_service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    logger.info("otel tracing configured -> %s", settings.otel_exporter_otlp_endpoint)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    _setup_tracing(settings)

    # Postgres pool — created once, reused for the process lifetime.
    app.state.pg_pool = await create_pool(settings)
    await ensure_schema(app.state.pg_pool)

    # Redis client — connection-pooled internally by redis-py.
    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)

    # Provider client — reads router:models from the same Redis client, so
    # a fine-tune promotion writing that key is visible immediately.
    try:
        app.state.llm_client = build_client(settings, app.state.redis)
    except RuntimeError as e:
        # Don't crash the whole API if no provider keys are set (e.g. a
        # dev environment that only needs /health and /metrics up) — log
        # loudly instead, since every generation call will fail until
        # this is fixed.
        logger.error("LLM client not initialized: %s", e)
        app.state.llm_client = None

    app.state.settings = settings

    # arq pool — used by POST /ingest and the generation pipeline to
    # enqueue jobs the worker process consumes (backend/worker_settings.py).
    # Separate from the plain redis.asyncio client above: arq's ArqRedis
    # wraps its own connection handling for job semantics (enqueue_job,
    # job IDs, etc).
    app.state.arq_pool = await create_arq_pool(settings.redis_url)

    logger.info("startup complete (env=%s)", settings.app_env)

    yield

    await app.state.arq_pool.close()
    await app.state.redis.aclose()
    await close_pool(app.state.pg_pool)
    logger.info("shutdown complete")


app = FastAPI(title="NeuroFlow API", version="0.1.0", lifespan=lifespan)

app.add_middleware(SecurityHeadersMiddleware)

# OpenTelemetry ASGI instrumentation — wired in from the start, per infra
# spec, rather than bolted on later.
FastAPIInstrumentor.instrument_app(app)

# /auth/token itself is unauthenticated (that's how you GET a token), and
# /health + /metrics are defined directly on `app` below (not via
# include_router), so they're naturally exempt from the auth dependency
# every other router gets here.
app.include_router(auth_api.router, tags=["auth"])

app.include_router(ingest_api.router, tags=["ingestion"], dependencies=[Depends(get_current_user)])
app.include_router(query_api.router, tags=["generation"], dependencies=[Depends(get_current_user)])
app.include_router(runs_api.router, tags=["evaluation"], dependencies=[Depends(get_current_user)])
app.include_router(pipelines_api.router, tags=["pipelines"], dependencies=[Depends(get_current_user)])
app.include_router(compare_api.router, tags=["pipelines"], dependencies=[Depends(get_current_user)])
app.include_router(finetune_api.router, tags=["finetuning"], dependencies=[Depends(get_current_user)])
app.include_router(chunks_api.router, tags=["chunks"], dependencies=[Depends(get_current_user)])
app.include_router(evaluations_api.router, tags=["evaluations"], dependencies=[Depends(get_current_user)])


@app.get("/health")
async def health(response: Response) -> dict:
    """Verifies real connectivity to Postgres, Redis, and MLflow (not just
    that clients were constructed at startup), plus resilience status:
    circuit breaker states, ingestion queue depth, and live worker count.

    status is "critical" if Postgres or Redis is unreachable (the API
    genuinely can't function), "degraded" if any circuit breaker is open
    (still serving, but a provider is failing over or unavailable), else
    "ok". Only "ok" returns 200 — both degraded and critical states are
    surfaced with a non-200 so a load balancer / orchestrator treats them
    as noteworthy, while still returning the full body either way so a
    human or dashboard can see exactly what's wrong.
    """
    settings = app.state.settings
    redis_client = getattr(app.state, "redis", None)

    postgres_check = await check_postgres_timed(getattr(app.state, "pg_pool", None))
    redis_check = await check_redis_timed(redis_client)
    mlflow_check = await check_mlflow_timed(settings.mlflow_tracking_uri)

    circuit_statuses = {}
    queue_depth = None
    worker_count = None
    if redis_client is not None:
        for provider_name in ("openai", "anthropic"):
            cb = circuit_breaker(provider_name, redis_client)
            circuit_statuses[provider_name] = await cb.get_status()
        queue_depth = await get_queue_depth(redis_client)
        worker_count = await get_worker_count(redis_client)

    postgres_ok = postgres_check["status"] == "ok"
    redis_ok = redis_check["status"] == "ok"
    any_circuit_open = any(c["state"] == "open" for c in circuit_statuses.values())

    if not postgres_ok or not redis_ok:
        status = "critical"
        response.status_code = 503
    elif any_circuit_open:
        status = "degraded"
        response.status_code = 503
    else:
        status = "ok"
        response.status_code = 200

    return {
        "status": status,
        "checks": {
            "postgres": postgres_check,
            "redis": redis_check,
            "mlflow": mlflow_check,
            "circuit_breakers": {
                name: {
                    "state": s["state"],
                    "failure_count": s["failure_count"],
                    **({"opened_at": s["opened_at"]} if s["opened_at"] is not None else {}),
                }
                for name, s in circuit_statuses.items()
            },
            "queue_depth": queue_depth,
            "worker_count": worker_count,
        },
    }


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus text-format exposition."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
