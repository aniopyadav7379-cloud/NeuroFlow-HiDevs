import hashlib
import ipaddress
import os
import socket
import uuid
from typing import Any
from urllib.parse import urlparse

import magic
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.config import settings
from backend.db.pool import get_pool
from backend.resilience.backpressure import check_ingest_backpressure
from backend.resilience.rate_limiter import rate_limit_endpoint
from backend.security.auth import RequireScope
from backend.security.prompt_injection import sanitize_text

router = APIRouter(tags=["Ingestion"])


def is_safe_url(url: str) -> bool:
    import re

    if not re.match(r"^https?://", url):
        return False
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname or hostname in ["localhost", "127.0.0.1", "::1"]:
        return False
    try:
        ip = socket.gethostbyname(hostname)
        ip_obj = ipaddress.ip_address(ip)
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
            return False
    except socket.gaierror:
        pass
    return True




class URLIngestRequest(BaseModel):
    url: str = Field(
        ...,
        description=(
            "The fully qualified HTTP/HTTPS URL to scrape and ingest into the knowledge base."
        ),
        examples=["https://en.wikipedia.org/wiki/Artificial_intelligence"],
        json_schema_extra={"example": "https://en.wikipedia.org/wiki/Artificial_intelligence"}
    )
    pipeline_id: str | None = Field(
        None, description="Optional pipeline ID to link the document to a specific pipeline."
    )

class IngestResponse(BaseModel):
    document_id: str = Field(..., description="The unique UUID assigned to the ingested document.")
    status: str = Field(..., description="The status of the ingestion process (e.g., 'queued').")
    duplicate: bool = Field(
        ..., description="True if the document was already ingested based on content hash."
    )
    warning: str | None = Field(None, description="Any backpressure warnings.")
    estimated_wait_minutes: int | None = Field(
        None, description="Estimated queue wait time if under heavy load."
    )


async def get_redis_pool() -> Any:  # noqa: ANN401
    return await create_pool(
        RedisSettings(
            host=settings.redis_host, port=settings.redis_port, password=settings.redis_password
        )
    )


UPLOAD_DIR = "/app/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post(
    "/ingest/file",
    dependencies=[Depends(rate_limit_endpoint(max_requests=10, window_seconds=3600))],
    summary="Upload and ingest a document file",
    description=(
        "Uploads a file (PDF, Docx, Text, Image) to be ingested into the knowledge base. "
        "This endpoint adds the document to an asynchronous queue for chunking and embedding. "
        "**Performance notes**: Rate limited to 10 requests per hour. Returns a 503 if the "
        "system is experiencing heavy backpressure. **Errors**: Triggers a 400 error for "
        "unsupported file types or files larger than 100MB."
    ),
    response_description=(
        "A JSON object containing the generated document_id, queue status, and deduplication flag."
    ),
    response_model=IngestResponse
)
async def ingest_file(
    file: UploadFile = File(...),
    pipeline_id: str | None = Form(None),
    redis: Any = Depends(get_redis_pool),  # noqa: ANN401
    user: Any = Depends(RequireScope("ingest")),  # noqa: ANN401
) -> Any:  # noqa: ANN401
    # Check Backpressure
    bp_warning = await check_ingest_backpressure()
    if bp_warning and bp_warning["status_code"] == 503:
        return JSONResponse(
            status_code=503, 
            content={
                "error": bp_warning["error"], 
                "queue_depth": bp_warning["queue_depth"], 
                "retry_after": bp_warning["retry_after"]
            }
        )

    filename_str = file.filename or "unknown"
    ext = filename_str.split(".")[-1].lower()
    if ext in ["pdf", "docx", "csv", "pptx"]:
        source_type = ext
    elif ext in ["jpeg", "jpg", "png", "webp"]:
        source_type = "image"
    elif ext in ["txt", "md"]:
        source_type = "text"
    else:
        raise HTTPException(400, "Unsupported file type")

    file_bytes = await file.read()
    if len(file_bytes) > 100 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 100MB)")

    mime = magic.from_buffer(file_bytes, mime=True)
    if mime in [
        "application/x-dosexec", 
        "application/x-executable", 
        "application/x-msdownload", 
        "application/x-sh"
    ]:
        raise HTTPException(400, "Executable files are strictly prohibited")

    if ext == "pdf" and mime != "application/pdf":
        raise HTTPException(400, "MIME type mismatch for PDF")

    content_hash = hashlib.sha256(file_bytes).hexdigest()
    filename = sanitize_text(filename_str)
    
    db_pool = get_pool()
    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id, status FROM documents WHERE content_hash = $1", content_hash
        )
        if existing:
            return IngestResponse(
                document_id=str(existing["id"]), 
                status=existing["status"], 
                duplicate=True,
                warning=None,
                estimated_wait_minutes=None
            )

        doc_id = str(uuid.uuid4())
        file_path = os.path.join(UPLOAD_DIR, f"{doc_id}_{filename}")
        with open(file_path, "wb") as f:  # noqa: ASYNC230
            f.write(file_bytes)
        worker_source_type = ext if source_type == "image" else source_type

        await conn.execute(
            """
            INSERT INTO documents (id, filename, source_type, content_hash, status) 
            VALUES ($1, $2, $3, $4, 'queued')
            """,
            doc_id, filename, source_type, content_hash,
        )

    await redis.enqueue_job(
        "process_document", doc_id, file_path, worker_source_type, _queue_name="queue:ingest"
    )

    if bp_warning:
        return JSONResponse(
            status_code=bp_warning["status_code"], 
            content={
                "document_id": doc_id, "status": "queued", "duplicate": False, 
                "warning": bp_warning["warning"], 
                "estimated_wait_minutes": bp_warning["estimated_wait_minutes"]
            }
        )

    return IngestResponse(
        document_id=doc_id, 
        status="queued", 
        duplicate=False,
        warning=None,
        estimated_wait_minutes=None
    )


@router.post(
    "/ingest/url",
    dependencies=[Depends(rate_limit_endpoint(max_requests=10, window_seconds=3600))],
    summary="Ingest a document via URL",
    description=(
        "Provides a URL to be ingested into the knowledge base via a JSON payload. "
        "This endpoint adds the document to an asynchronous queue for crawling and embedding. "
        "**Errors**: Triggers a 400 error for Server-Side Request Forgery (SSRF) attempts "
        "on local IP addresses."
    ),
    response_description=(
        "A JSON object containing the generated document_id, queue status, and deduplication flag."
    ),
    response_model=IngestResponse
)
async def ingest_url(
    payload: URLIngestRequest,
    redis: Any = Depends(get_redis_pool),  # noqa: ANN401
    user: Any = Depends(RequireScope("ingest")),  # noqa: ANN401
) -> Any:  # noqa: ANN401
    bp_warning = await check_ingest_backpressure()
    if bp_warning and bp_warning["status_code"] == 503:
        return JSONResponse(
            status_code=503, 
            content={
                "error": bp_warning["error"], 
                "queue_depth": bp_warning["queue_depth"], 
                "retry_after": bp_warning["retry_after"]
            }
        )

    url = sanitize_text(payload.url)
    if not is_safe_url(url):
        raise HTTPException(400, "Invalid or prohibited URL (SSRF protection)")

    content_hash = hashlib.sha256(url.encode()).hexdigest()
    filename = url
    
    db_pool = get_pool()
    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id, status FROM documents WHERE content_hash = $1", content_hash
        )
        if existing:
            return IngestResponse(
                document_id=str(existing["id"]), 
                status=existing["status"], 
                duplicate=True,
                warning=None,
                estimated_wait_minutes=None
            )

        doc_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO documents (id, filename, source_type, content_hash, status) 
            VALUES ($1, $2, $3, $4, 'queued')
            """,
            doc_id, filename, "url", content_hash,
        )

    await redis.enqueue_job(
        "process_document", doc_id, url, "url", _queue_name="queue:ingest"
    )

    if bp_warning:
        return JSONResponse(
            status_code=bp_warning["status_code"], 
            content={
                "document_id": doc_id, "status": "queued", "duplicate": False, 
                "warning": bp_warning["warning"], 
                "estimated_wait_minutes": bp_warning["estimated_wait_minutes"]
            }
        )

    return IngestResponse(
        document_id=doc_id, 
        status="queued", 
        duplicate=False,
        warning=None,
        estimated_wait_minutes=None
    )


@router.get(
    "/documents/{document_id}",
    summary="Get document ingestion status",
    description=(
        "Poll this endpoint to check the asynchronous processing status of an ingested document. "
        "Use this to determine when a document is fully chunked, embedded, and ready for querying "
        "(status will be `complete`). **Errors**: Triggers a 400 for an invalid UUID format, "
        "or a 404 if the document ID does not exist in the database."
    ),
    response_description=(
        "A JSON object containing the current processing status, "
        "chunk count, and extracted metadata."
    )
)
async def get_document_status(document_id: str, request: Request) -> Any:  # noqa: ANN401
    db_pool = get_pool()

    try:
        uuid.UUID(document_id)
    except:  # noqa: E722
        raise HTTPException(400, "Invalid document ID")

    async with db_pool.acquire() as conn:
        doc = await conn.fetchrow(
            "SELECT status, chunk_count, metadata FROM documents WHERE id = $1", document_id
        )

    if not doc:
        raise HTTPException(404, "Document not found")

    return {"status": doc["status"], "chunk_count": doc["chunk_count"], "metadata": doc["metadata"]}
