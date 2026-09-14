from typing import Any

import asyncpg
import redis.asyncio as aioredis
from arq.connections import RedisSettings
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from backend.config import settings
from backend.providers.client import NeuroFlowClient
from pipelines.ingestion.pipeline import process_document_pipeline


async def startup(ctx: Any) -> Any:  # noqa: ANN401
    resource = Resource.create({"service.name": "neuroflow-worker"})
    provider = TracerProvider(resource=resource)

    # In local testing we might point to localhost, but jaeger is usually available via docker network  # noqa: E501
    jaeger_endpoint = (
        "http://jaeger:4317" if settings.postgres_host == "postgres" else "http://localhost:4317"
    )
    try:
        exporter = OTLPSpanExporter(endpoint=jaeger_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
    except Exception:
        pass

    ctx["db_pool"] = await asyncpg.create_pool(
        host=settings.postgres_host,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database=settings.postgres_db,
        port=settings.postgres_port,
    )

    redis_client = aioredis.from_url(
        f"redis://:{settings.redis_password}@{settings.redis_host}:{settings.redis_port}",
        decode_responses=True,
    )
    ctx["llm_client"] = NeuroFlowClient(redis_client=redis_client)


async def shutdown(ctx: Any) -> Any:  # noqa: ANN401
    await ctx["db_pool"].close()


async def process_document(ctx: Any, document_id: str, file_path: str, source_type: str) -> Any:  # noqa: ANN401
    await process_document_pipeline(
        db_pool=ctx["db_pool"],
        client=ctx["llm_client"],
        document_id=document_id,
        file_path=file_path,
        source_type=source_type,
    )


from arq.cron import cron  # noqa: E402

from pipelines.finetuning.job_manager import poll_finetune_jobs  # noqa: E402


class WorkerSettings:
    functions = [process_document]
    cron_jobs = [cron(poll_finetune_jobs, second=0)]
    redis_settings = RedisSettings(
        host=settings.redis_host, port=settings.redis_port, password=settings.redis_password
    )
    on_startup = startup
    on_shutdown = shutdown
