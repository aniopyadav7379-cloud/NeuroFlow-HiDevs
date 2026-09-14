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
from pydantic import BaseModel

from backend.config import settings
from backend.db.pool import get_pool
from backend.resilience.backpressure import check_ingest_backpressure
from backend.resilience.rate_limiter import rate_limit_endpoint
from backend.security.auth import RequireScope
from backend.security.prompt_injection import sanitize_text

router = APIRouter()


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
    url: str


async def get_redis_pool() -> Any:  # noqa: ANN401
    return await create_pool(
        RedisSettings(
            host=settings.redis_host, port=settings.redis_port, password=settings.redis_password
        )
    )


UPLOAD_DIR = "/app/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post(
    "/ingest", dependencies=[Depends(rate_limit_endpoint(max_requests=10, window_seconds=3600))]
)
async def ingest_document(
    request: Request,
    file: UploadFile | None = File(None),
    url: str | None = Form(None),
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
                "retry_after": bp_warning["retry_after"],
            },
        )

    # Determine type
    source_type = None
    file_bytes = None
    content_hash = None
    filename = None

    if file:
        ext = file.filename.split(".")[-1].lower()  # type: ignore
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

        # Magic bytes check
        mime = magic.from_buffer(file_bytes, mime=True)
        if mime in [
            "application/x-dosexec",
            "application/x-executable",
            "application/x-msdownload",
            "application/x-sh",
        ]:
            raise HTTPException(400, "Executable files are strictly prohibited")

        # Simple cross-check (MIME vs Ext)
        if ext == "pdf" and mime != "application/pdf":
            raise HTTPException(400, "MIME type mismatch for PDF")

        content_hash = hashlib.sha256(file_bytes).hexdigest()
        filename = sanitize_text(file.filename)  # type: ignore

    else:
        # Check if json body was passed
        try:
            body = await request.json()
            url = body.get("url")
        except:  # noqa: E722
            pass

        if url:
            url = sanitize_text(url)
            if not is_safe_url(url):
                raise HTTPException(400, "Invalid or prohibited URL (SSRF protection)")
            source_type = "url"
            content_hash = hashlib.sha256(url.encode()).hexdigest()
            filename = url
            file_bytes = None
        else:
            raise HTTPException(400, "Must provide file or url")

    db_pool = get_pool()

    # Check deduplication
    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id, status FROM documents WHERE content_hash = $1", content_hash
        )
        if existing:
            return {
                "document_id": str(existing["id"]),
                "status": existing["status"],
                "duplicate": True,
            }

        doc_id = str(uuid.uuid4())

        # Save file to shared volume if not URL
        if file_bytes:
            file_path = os.path.join(UPLOAD_DIR, f"{doc_id}_{filename}")
            with open(file_path, "wb") as f:  # noqa: ASYNC230
                f.write(file_bytes)
            worker_source_type = ext if source_type == "image" else source_type
        else:
            file_path = str(url)  # for url extractor, we just pass the URL
            worker_source_type = "url"

        await conn.execute(
            """
            INSERT INTO documents (id, filename, source_type, content_hash, status)
            VALUES ($1, $2, $3, $4, 'queued')
            """,
            doc_id,
            filename,
            source_type,
            content_hash,
        )

    # Enqueue job specifying the custom queue name if we want to ensure it goes to queue:ingest
    # By default, ARQ uses 'arq:queue'. We will explicitly push to the queue the prompt requested:
    # Actually, ARQ's enqueue_job does not have a parameter to change the queue dynamically unless defined in RedisSettings.  # noqa: E501
    # To be perfectly safe for the prompt "LLEN queue:ingest", we will push a dummy key or configure ARQ in worker.py.  # noqa: E501
    # Let's just enqueue normal for now.
    await redis.enqueue_job(
        "process_document", doc_id, file_path, worker_source_type, _queue_name="queue:ingest"
    )

    if bp_warning:
        return JSONResponse(
            status_code=bp_warning["status_code"],
            content={
                "document_id": doc_id,
                "status": "queued",
                "duplicate": False,
                "warning": bp_warning["warning"],
                "estimated_wait_minutes": bp_warning["estimated_wait_minutes"],
            },
        )

    return {"document_id": doc_id, "status": "queued", "duplicate": False}


@router.get("/documents/{document_id}")
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
