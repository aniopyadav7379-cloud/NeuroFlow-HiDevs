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
from fastapi import FastAPI, Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from backend.config import get_settings
from backend.db.health import check_mlflow, check_postgres, check_redis
from backend.db.migrations import ensure_schema
from backend.db.pool import close_pool, create_pool
from backend.providers.client import build_client
from backend.api import ingest as ingest_api
from backend.api import query as query_api
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

    # arq pool — used by POST /ingest to enqueue jobs the worker process
    # consumes (pipelines/ingestion/worker_settings.py). Separate from the
    # plain redis.asyncio client above: arq's ArqRedis wraps its own
    # connection handling for job semantics (enqueue_job, job IDs, etc).
    app.state.arq_pool = await create_arq_pool(settings.redis_url)

    logger.info("startup complete (env=%s)", settings.app_env)

    yield

    await app.state.arq_pool.close()
    await app.state.redis.aclose()
    await close_pool(app.state.pg_pool)
    logger.info("shutdown complete")


app = FastAPI(title="NeuroFlow API", version="0.1.0", lifespan=lifespan)

# OpenTelemetry ASGI instrumentation — wired in from the start, per infra
# spec, rather than bolted on later.
FastAPIInstrumentor.instrument_app(app)

app.include_router(ingest_api.router, tags=["ingestion"])
app.include_router(query_api.router, tags=["generation"])


@app.get("/health")
async def health(response: Response) -> dict:
    """Verifies real connectivity to Postgres, Redis, and MLflow — not just
    that the process is up. Returns 200 only if all three pass; 503 if any
    fail, so this is safe to point a load balancer / orchestrator at."""
    settings = app.state.settings

    postgres_ok = await check_postgres(getattr(app.state, "pg_pool", None))
    redis_ok = await check_redis(getattr(app.state, "redis", None))
    mlflow_ok = await check_mlflow(settings.mlflow_tracking_uri)

    all_ok = postgres_ok and redis_ok and mlflow_ok
    response.status_code = 200 if all_ok else 503

    return {
        "status": "ok" if all_ok else "degraded",
        "checks": {
            "postgres": postgres_ok,
            "redis": redis_ok,
            "mlflow": mlflow_ok,
        },
    }


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus text-format exposition."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
