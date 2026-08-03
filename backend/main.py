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

    app.state.settings = settings
    logger.info("startup complete (env=%s)", settings.app_env)

    yield

    await app.state.redis.aclose()
    await close_pool(app.state.pg_pool)
    logger.info("shutdown complete")


app = FastAPI(title="NeuroFlow API", version="0.1.0", lifespan=lifespan)

# OpenTelemetry ASGI instrumentation — wired in from the start, per infra
# spec, rather than bolted on later.
FastAPIInstrumentor.instrument_app(app)


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
