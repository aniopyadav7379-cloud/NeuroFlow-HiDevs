"""
Parallel hybrid retrieval: dense (pgvector HNSW), sparse (Postgres
full-text, cover-density ranked), and metadata-filtered dense retrieval,
run concurrently via asyncio.gather and merged with Reciprocal Rank Fusion.
"""
import asyncio
import json
import logging

import asyncpg

from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria
from pipelines.retrieval.fusion import reciprocal_rank_fusion
from pipelines.retrieval.query_processor import ProcessedQuery, process_query
from pipelines.retrieval.types import RetrievalResult

logger = logging.getLogger("neuroflow.retrieval.retriever")

DEFAULT_K = 20


def _row_to_result(row: asyncpg.Record, score: float, method: str) -> RetrievalResult:
    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    return RetrievalResult(
        chunk_id=str(row["id"]),
        content=row["content"],
        score=score,
        metadata=metadata or {},
        document_id=str(row["document_id"]) if row["document_id"] else None,
        retrieval_method=method,
    )


def _union_by_max_score(result_sets: list[list[RetrievalResult]]) -> list[RetrievalResult]:
    """Used to merge dense retrieval across the original query + expanded
    query phrasings (task spec: "retrieve for each expanded query and
    union results") — a chunk found under multiple phrasings keeps its
    best (max) similarity score rather than being counted multiple times
    into RRF, which would double-count it under retrieval_method='dense'
    alone."""
    best: dict[str, RetrievalResult] = {}
    for results in result_sets:
        for r in results:
            existing = best.get(r.chunk_id)
            if existing is None or r.score > existing.score:
                best[r.chunk_id] = r
    merged = list(best.values())
    merged.sort(key=lambda r: r.score, reverse=True)
    return merged


class Retriever:
    def __init__(self, pool: asyncpg.Pool, llm_client: NeuroFlowClient):
        self.pool = pool
        self.llm_client = llm_client

    async def _dense_retrieval(self, query_texts: list[str], k: int) -> list[RetrievalResult]:
        """Embeds every query text (original + expansions) and searches
        pgvector for each, then unions by max score (see _union_by_max_score)."""
        if not query_texts:
            return []

        vectors = await self.llm_client.embed(query_texts, RoutingCriteria(task_type="embedding"))

        async def _search_one(vector: list[float]) -> list[RetrievalResult]:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, document_id, content, metadata,
                           1 - (embedding <=> $1::vector) AS similarity
                    FROM chunks
                    ORDER BY embedding <=> $1::vector
                    LIMIT $2
                    """,
                    str(vector), k,
                )
            return [_row_to_result(row, row["similarity"], "dense") for row in rows]

        per_query_results = await asyncio.gather(*(_search_one(v) for v in vectors))
        return _union_by_max_score(list(per_query_results))

    async def _sparse_retrieval(self, query: str, k: int) -> list[RetrievalResult]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, document_id, content, metadata,
                       ts_rank_cd(to_tsvector('english', content), plainto_tsquery('english', $1)) AS rank
                FROM chunks
                WHERE to_tsvector('english', content) @@ plainto_tsquery('english', $1)
                ORDER BY rank DESC
                LIMIT $2
                """,
                query, k,
            )
        return [_row_to_result(row, row["rank"], "sparse") for row in rows]

    async def _metadata_retrieval(self, query: str, filters: dict, k: int) -> list[RetrievalResult]:
        """Independent embed + search, so this coroutine has no data
        dependency on the dense branch and can run in the same
        asyncio.gather as dense/sparse (task spec: all three in parallel).
        Costs one extra embedding call versus sharing the dense branch's
        vector, traded for genuine concurrency rather than a sequential
        await before the gather."""
        if not filters:
            return []
        vectors = await self.llm_client.embed([query], RoutingCriteria(task_type="embedding"))
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, document_id, content, metadata,
                       1 - (embedding <=> $2::vector) AS similarity
                FROM chunks
                WHERE metadata @> $1::jsonb
                ORDER BY embedding <=> $2::vector
                LIMIT $3
                """,
                json.dumps(filters), str(vectors[0]), k,
            )
        return [_row_to_result(row, row["similarity"], "metadata") for row in rows]

    async def retrieve(
        self,
        query: str,
        k: int = DEFAULT_K,
        *,
        dense_k: int | None = None,
        sparse_k: int | None = None,
        metadata_k: int | None = None,
        processed: ProcessedQuery | None = None,
        use_hyde: bool = False,
        enable_query_expansion: bool = True,
    ) -> list[RetrievalResult]:
        """Full pipeline: process the query (expansion/filters/type, unless
        already provided by the caller), run dense/sparse/metadata in
        parallel, fuse with RRF. `processed` lets callers that already ran
        process_query() (e.g. to reuse query_type downstream) skip re-running
        it here. `dense_k`/`sparse_k`/`metadata_k` (from a pipeline's
        retrieval config) override the single `k` for each strategy
        independently — falls back to `k` for any that aren't given, so
        existing callers passing only `k` are unaffected."""
        dense_k = dense_k if dense_k is not None else k
        sparse_k = sparse_k if sparse_k is not None else k
        metadata_k = metadata_k if metadata_k is not None else k

        if processed is None:
            processed = await process_query(query, self.llm_client, enable_expansion=enable_query_expansion)

        dense_query_texts = processed.all_queries
        if use_hyde:
            from pipelines.retrieval.hyde import generate_hypothetical_answer
            hyde_text = await generate_hypothetical_answer(query, self.llm_client)
            if hyde_text:
                dense_query_texts = [hyde_text] + processed.expanded_queries

        dense_results, sparse_results, metadata_results = await asyncio.gather(
            self._dense_retrieval(dense_query_texts, dense_k),
            self._sparse_retrieval(query, sparse_k),
            self._metadata_retrieval(query, processed.metadata_filters, metadata_k),
        )

        return reciprocal_rank_fusion([dense_results, sparse_results, metadata_results])
