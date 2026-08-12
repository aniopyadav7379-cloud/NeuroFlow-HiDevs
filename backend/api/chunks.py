"""
Chunk-level lookups for the frontend: full content for the citation
drawer (Page 1) and embedding-similarity search for the document detail
page's "Find similar chunks" (Page 4).
"""
import json
import logging

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("neuroflow.api.chunks")
router = APIRouter()


@router.get("/chunks/{chunk_id}")
async def get_chunk(request: Request, chunk_id: str):
    pool = request.app.state.pg_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, document_id, content, chunk_index, metadata FROM chunks WHERE id = $1", chunk_id
        )
    if row is None:
        raise HTTPException(status_code=404, detail=f"chunk {chunk_id} not found")

    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)

    return {
        "id": str(row["id"]),
        "document_id": str(row["document_id"]) if row["document_id"] else None,
        "content": row["content"],
        "chunk_index": row["chunk_index"],
        "metadata": metadata or {},
    }


@router.get("/chunks/{chunk_id}/similar")
async def find_similar_chunks(request: Request, chunk_id: str, limit: int = 10):
    """Embeds nothing new — reuses the chunk's own stored embedding as the
    query vector for pgvector cosine search, matching the "Find similar
    chunks" feature in the Documents page (searches across ALL chunks,
    not just this document, per the task spec)."""
    pool = request.app.state.pg_pool

    async with pool.acquire() as conn:
        source = await conn.fetchrow("SELECT embedding FROM chunks WHERE id = $1", chunk_id)
        if source is None or source["embedding"] is None:
            raise HTTPException(status_code=404, detail=f"chunk {chunk_id} not found or has no embedding")

        rows = await conn.fetch(
            """
            SELECT id, document_id, content, chunk_index,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM chunks
            WHERE id != $2 AND embedding IS NOT NULL
            ORDER BY embedding <=> $1::vector
            LIMIT $3
            """,
            source["embedding"], chunk_id, limit,
        )

    return {
        "chunks": [
            {
                "id": str(r["id"]),
                "document_id": str(r["document_id"]) if r["document_id"] else None,
                "content": r["content"],
                "chunk_index": r["chunk_index"],
                "similarity": r["similarity"],
            }
            for r in rows
        ]
    }
