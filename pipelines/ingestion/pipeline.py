"""
The ingestion orchestrator: extract -> chunk -> embed -> write, run as an
arq job in the worker process (never in the API — see backend/api/ingest.py,
which only enqueues and returns).

This is the concrete implementation of docs/architecture.md §1's data flow:
file/URL -> ExtractedDocument -> Chunker -> Embedder -> Postgres/pgvector,
plus the OTel span (`ingestion.process`) and structured completion log the
task's observability requirements call for.
"""
import json
import logging
import time
from pathlib import Path

from opentelemetry import trace

from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria
from pipelines.ingestion.chunker import Chunk, chunk_fixed_size, chunk_hierarchical, chunk_semantic, select_strategy
from pipelines.ingestion.extractors.base import ExtractedPage
from pipelines.ingestion.extractors.csv_extractor import extract_csv
from pipelines.ingestion.extractors.docx_extractor import extract_docx, has_headings
from pipelines.ingestion.extractors.image_extractor import extract_image
from pipelines.ingestion.extractors.pdf_extractor import extract_pdf
from pipelines.ingestion.extractors.pptx_extractor import extract_pptx
from pipelines.ingestion.extractors.url_extractor import extract_url

logger = logging.getLogger("neuroflow.ingestion.pipeline")
tracer = trace.get_tracer("neuroflow.ingestion")

EMBED_BATCH_SIZE = 100


class IngestionError(Exception):
    pass


async def _extract(source_type: str, file_path: str | None, url: str | None, llm_client: NeuroFlowClient):
    """Returns (pages, doc_has_headings, page_count_for_strategy)."""
    if source_type == "pdf":
        data = Path(file_path).read_bytes()
        pages = extract_pdf(data)
        text_page_count = sum(1 for p in pages if p.content_type == "text")
        return pages, False, text_page_count

    if source_type == "docx":
        data = Path(file_path).read_bytes()
        pages = extract_docx(data)
        return pages, has_headings(data), len(pages)

    if source_type == "image":
        data = Path(file_path).read_bytes()
        pages = await extract_image(data, llm_client, filename=Path(file_path).name)
        return pages, False, len(pages)

    if source_type == "csv":
        data = Path(file_path).read_bytes()
        pages = extract_csv(data)
        return pages, False, len(pages)

    if source_type == "pptx":
        data = Path(file_path).read_bytes()
        pages = await extract_pptx(data, llm_client)
        return pages, False, len(pages)

    if source_type == "url":
        if not url:
            raise IngestionError("source_type='url' requires a url")
        pages = await extract_url(url)
        return pages, False, len(pages)

    raise IngestionError(f"unsupported source_type: {source_type!r}")


async def _chunk_pages(
    pages: list[ExtractedPage], *, source_type: str, page_count: int, doc_has_headings: bool, llm_client: NeuroFlowClient
) -> list[Chunk]:
    strategies = [
        select_strategy(p, source_type=source_type, page_count=page_count, doc_has_headings=doc_has_headings)
        for p in pages
    ]

    hierarchical_pages = [p for p, s in zip(pages, strategies) if s == "hierarchical"]
    chunks: list[Chunk] = []
    if hierarchical_pages:
        chunks.extend(chunk_hierarchical(hierarchical_pages))

    async def _embed_fn(texts: list[str]) -> list[list[float]]:
        return await llm_client.embed(texts, RoutingCriteria(task_type="embedding"))

    for page, strategy in zip(pages, strategies):
        if strategy == "hierarchical":
            continue  # already handled above, as a group
        if strategy == "semantic":
            chunks.extend(await chunk_semantic(page.content, page.metadata, embed_fn=_embed_fn))
        else:
            chunks.extend(chunk_fixed_size(page.content, page.metadata))

    return chunks


async def _embed_and_persist(pool, document_id: str, chunks: list[Chunk], llm_client: NeuroFlowClient) -> int:
    """Embeds chunks in batches and writes them to `chunks`. Returns the
    number of embed() calls made (the `embedding_calls` OTel attribute)."""
    embedding_calls = 0

    async with pool.acquire() as conn:
        for batch_start in range(0, len(chunks), EMBED_BATCH_SIZE):
            batch = chunks[batch_start : batch_start + EMBED_BATCH_SIZE]
            vectors = await llm_client.embed([c.text for c in batch], RoutingCriteria(task_type="embedding"))
            embedding_calls += 1

            rows = [
                (
                    document_id,
                    chunk.text,
                    str(vector),  # asyncpg + pgvector: pass as a string literal, cast in SQL
                    batch_start + i,
                    chunk.token_count,
                    json.dumps(chunk.metadata),
                )
                for i, (chunk, vector) in enumerate(zip(batch, vectors))
            ]
            await conn.executemany(
                """
                INSERT INTO chunks (document_id, content, embedding, chunk_index, token_count, metadata)
                VALUES ($1, $2, $3::vector, $4, $5, $6::jsonb)
                """,
                rows,
            )

    return embedding_calls


async def process_document_job(
    ctx: dict,
    *,
    document_id: str,
    file_path: str | None,
    source_type: str,
    pipeline_id: str | None = None,
) -> None:
    """The arq job function registered in worker_settings.WorkerSettings.functions."""
    pool = ctx["pg_pool"]
    llm_client: NeuroFlowClient = ctx["llm_client"]

    redis_client = ctx.get("redis")
    if redis_client is not None:
        from backend.resilience.backpressure import decrement_queue_depth
        await decrement_queue_depth(redis_client)

    started = time.perf_counter()

    async with pool.acquire() as conn:
        await conn.execute("UPDATE documents SET status = 'processing' WHERE id = $1", document_id)
        doc_row = await conn.fetchrow("SELECT metadata FROM documents WHERE id = $1", document_id)

    url = None
    if doc_row and doc_row["metadata"]:
        meta = doc_row["metadata"] if isinstance(doc_row["metadata"], dict) else json.loads(doc_row["metadata"])
        url = meta.get("url")

    with tracer.start_as_current_span("ingestion.process") as span:
        span.set_attribute("document_id", document_id)
        span.set_attribute("source_type", source_type)

        try:
            pages, doc_has_headings, page_count = await _extract(source_type, file_path, url, llm_client)
            span.set_attribute("page_count", page_count)

            chunks = await _chunk_pages(
                pages, source_type=source_type, page_count=page_count, doc_has_headings=doc_has_headings, llm_client=llm_client
            )
            span.set_attribute("chunk_count", len(chunks))

            embedding_calls = await _embed_and_persist(pool, document_id, chunks, llm_client)
            span.set_attribute("embedding_calls", embedding_calls)

            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE documents SET status = 'complete', chunk_count = $2 WHERE id = $1",
                    document_id, len(chunks),
                )

        except Exception:
            async with pool.acquire() as conn:
                await conn.execute("UPDATE documents SET status = 'failed' WHERE id = $1", document_id)
            span.set_attribute("error", True)
            logger.exception("ingestion failed for document_id=%s", document_id)
            raise

    duration_ms = (time.perf_counter() - started) * 1000
    total_tokens = sum(c.token_count for c in chunks)
    logger.info(json.dumps({
        "event": "ingestion_complete",
        "document_id": document_id,
        "duration_ms": round(duration_ms, 1),
        "chunks": len(chunks),
        "tokens": total_tokens,
    }))
