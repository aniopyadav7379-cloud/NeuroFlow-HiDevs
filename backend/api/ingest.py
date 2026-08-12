"""
POST /ingest and GET /documents/{document_id} — the only ingestion-related
HTTP surface. Everything past "accept the upload, dedupe, enqueue" happens
in the worker (pipelines/ingestion/pipeline.py); this module does no
extraction, chunking, or embedding itself, so it can return immediately
per the task's "POST /ingest returns immediately" requirement.
"""
import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from backend.resilience.backpressure import check_backpressure, increment_queue_depth
from backend.resilience.rate_limit_dependency import rate_limit
from pipelines.ingestion.dedup import compute_content_hash, find_existing_document
from pipelines.ingestion.queue import enqueue_ingestion_job

logger = logging.getLogger("neuroflow.api.ingest")
router = APIRouter()

INGEST_RATE_LIMIT = rate_limit(10, 3600, key_prefix="ingest")  # 10 requests/hour per IP

EXTENSION_TO_SOURCE_TYPE = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".webp": "image",
    ".csv": "csv",
    ".pptx": "pptx",
}


class UrlIngestRequest(BaseModel):
    url: str
    pipeline_id: str | None = None


class IngestResponse(BaseModel):
    document_id: str
    status: str
    duplicate: bool
    warning: str | None = None
    estimated_wait_minutes: float | None = None


class DocumentStatusResponse(BaseModel):
    document_id: str
    filename: str
    source_type: str
    status: str
    chunk_count: int | None
    metadata: dict
    created_at: str


def _source_type_for_filename(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    source_type = EXTENSION_TO_SOURCE_TYPE.get(ext)
    if source_type is None:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported file extension '{ext}' (supported: {sorted(EXTENSION_TO_SOURCE_TYPE)})",
        )
    return source_type


async def _create_document_row(pool, *, filename: str, source_type: str, content_hash: str, metadata: dict, pipeline_id: str | None) -> str:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO documents (filename, source_type, content_hash, metadata, pipeline_id, status)
            VALUES ($1, $2, $3, $4::jsonb, $5, 'queued')
            RETURNING id
            """,
            filename, source_type, content_hash, json.dumps(metadata), pipeline_id,
        )
    return str(row["id"])


async def _backpressure_or_none(request: Request):
    """Returns a JSONResponse to short-circuit with (503 full, per task
    spec's exact body shape — NOT wrapped in HTTPException's {"detail":
    ...}) if the queue is full, a warning dict to merge into the normal
    response if the queue is high-but-not-full, or None if depth is
    healthy."""
    from fastapi.responses import JSONResponse

    decision = await check_backpressure(request.app.state.redis)
    if not decision.allowed:
        return JSONResponse(status_code=decision.status_code, content=decision.body)
    if decision.status_code == 202:
        return decision.body  # dict — caller merges into the real response
    return None


@router.post("/ingest", response_model=IngestResponse, status_code=202, dependencies=[Depends(INGEST_RATE_LIMIT)])
async def ingest(request: Request, file: UploadFile | None = File(default=None)) -> IngestResponse:
    pool = request.app.state.pg_pool
    arq_pool = request.app.state.arq_pool

    backpressure_result = await _backpressure_or_none(request)
    if backpressure_result is not None and not isinstance(backpressure_result, dict):
        return backpressure_result  # JSONResponse: queue full, 503

    if file is not None:
        settings = request.app.state.settings
        content_bytes = await file.read()
        max_bytes = settings.max_upload_size_mb * 1024 * 1024
        if len(content_bytes) > max_bytes:
            raise HTTPException(status_code=413, detail=f"file exceeds max upload size ({settings.max_upload_size_mb}MB)")

        source_type = _source_type_for_filename(file.filename or "")
        content_hash = compute_content_hash(content_bytes)

        existing_id = await find_existing_document(pool, content_hash)
        if existing_id:
            async with pool.acquire() as conn:
                existing_status = await conn.fetchval("SELECT status FROM documents WHERE id = $1", existing_id)
            logger.info("duplicate upload detected, reusing document_id=%s", existing_id)
            return IngestResponse(document_id=existing_id, status=existing_status, duplicate=True)

        upload_dir = Path(settings.upload_dir)
        upload_dir.mkdir(parents=True, exist_ok=True)
        stored_filename = f"{uuid.uuid4()}_{file.filename}"
        file_path = upload_dir / stored_filename
        file_path.write_bytes(content_bytes)

        document_id = await _create_document_row(
            pool,
            filename=file.filename or stored_filename,
            source_type=source_type,
            content_hash=content_hash,
            metadata={},
            pipeline_id=None,
        )
        await enqueue_ingestion_job(
            arq_pool,
            document_id=document_id,
            file_path=str(file_path),
            source_type=source_type,
            pipeline_id=None,
        )
        await increment_queue_depth(request.app.state.redis)

        warning = backpressure_result or {}
        return IngestResponse(document_id=document_id, status="queued", duplicate=False, **warning)

    # No file part — per spec, /ingest also accepts a plain JSON body
    # ({"url": "..."}) for URL ingestion instead of a multipart file.
    try:
        body = await request.json()
    except Exception:
        body = None
    if isinstance(body, dict) and body.get("url"):
        return await _handle_url_ingest(request, url=body["url"], pipeline_id=body.get("pipeline_id"))

    raise HTTPException(status_code=400, detail="either a file upload or a JSON {\"url\": ...} body is required")


async def _handle_url_ingest(request: Request, *, url: str, pipeline_id: str | None) -> IngestResponse:
    pool = request.app.state.pg_pool
    arq_pool = request.app.state.arq_pool

    backpressure_result = await _backpressure_or_none(request)
    if backpressure_result is not None and not isinstance(backpressure_result, dict):
        return backpressure_result  # JSONResponse: queue full, 503

    content_hash = compute_content_hash(url.encode("utf-8"))
    existing_id = await find_existing_document(pool, content_hash)
    if existing_id:
        async with pool.acquire() as conn:
            existing_status = await conn.fetchval("SELECT status FROM documents WHERE id = $1", existing_id)
        logger.info("duplicate URL ingest detected, reusing document_id=%s", existing_id)
        return IngestResponse(document_id=existing_id, status=existing_status, duplicate=True)

    document_id = await _create_document_row(
        pool,
        filename=url,
        source_type="url",
        content_hash=content_hash,
        metadata={"url": url},
        pipeline_id=pipeline_id,
    )
    await enqueue_ingestion_job(
        arq_pool,
        document_id=document_id,
        file_path=None,
        source_type="url",
        pipeline_id=pipeline_id,
    )
    await increment_queue_depth(request.app.state.redis)

    warning = backpressure_result or {}
    return IngestResponse(document_id=document_id, status="queued", duplicate=False, **warning)


@router.post("/ingest/url", response_model=IngestResponse, status_code=202, dependencies=[Depends(INGEST_RATE_LIMIT)])
async def ingest_url(request: Request, body: UrlIngestRequest) -> IngestResponse:
    """Convenience alias for JSON-only clients that don't want to send a
    multipart body to POST /ingest at all — same handling either way."""
    return await _handle_url_ingest(request, url=body.url, pipeline_id=body.pipeline_id)


@router.get("/documents/{document_id}", response_model=DocumentStatusResponse)
async def get_document(request: Request, document_id: str) -> DocumentStatusResponse:
    pool = request.app.state.pg_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, filename, source_type, status, chunk_count, metadata, created_at
            FROM documents WHERE id = $1
            """,
            document_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail=f"document {document_id} not found")

    metadata = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
    return DocumentStatusResponse(
        document_id=str(row["id"]),
        filename=row["filename"],
        source_type=row["source_type"],
        status=row["status"],
        chunk_count=row["chunk_count"],
        metadata=metadata,
        created_at=row["created_at"].isoformat(),
    )


@router.get("/documents")
async def list_documents(request: Request, limit: int = 100):
    """Lists ingested documents — used by the frontend Documents page
    table. GET /documents/{id} (single-doc status) already existed for
    the ingestion-status poll; this is the list view the table needs."""
    pool = request.app.state.pg_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, filename, source_type, status, chunk_count, metadata, created_at
            FROM documents ORDER BY created_at DESC LIMIT $1
            """,
            limit,
        )

    def _meta(row):
        m = row["metadata"]
        return json.loads(m) if isinstance(m, str) else (m or {})

    return {
        "documents": [
            {
                "document_id": str(r["id"]),
                "filename": r["filename"],
                "source_type": r["source_type"],
                "status": r["status"],
                "chunk_count": r["chunk_count"],
                "metadata": _meta(r),
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/documents/{document_id}/chunks")
async def get_document_chunks(request: Request, document_id: str, limit: int = 200):
    pool = request.app.state.pg_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, content, chunk_index, metadata FROM chunks
            WHERE document_id = $1 ORDER BY chunk_index LIMIT $2
            """,
            document_id, limit,
        )

    def _meta(row):
        m = row["metadata"]
        return json.loads(m) if isinstance(m, str) else (m or {})

    return {
        "chunks": [
            {"id": str(r["id"]), "content": r["content"], "chunk_index": r["chunk_index"], "metadata": _meta(r)}
            for r in rows
        ]
    }
