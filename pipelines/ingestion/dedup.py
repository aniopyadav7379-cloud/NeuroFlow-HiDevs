"""
Deduplication: sha256(file_bytes) is compared against documents.content_hash
(UNIQUE, see infra/init/001_schema.sql) before any extraction/chunking/
embedding work happens — embedding calls cost money, so a repeat upload of
the same bytes should never re-run the pipeline.
"""
import hashlib

import asyncpg


def compute_content_hash(content_bytes: bytes) -> str:
    return hashlib.sha256(content_bytes).hexdigest()


async def find_existing_document(pool: asyncpg.Pool, content_hash: str) -> str | None:
    """Returns the existing document_id if this content_hash has already
    been ingested, else None."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM documents WHERE content_hash = $1", content_hash
        )
    return str(row["id"]) if row else None
