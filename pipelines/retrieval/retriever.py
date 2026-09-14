import asyncio
import json
import time

import asyncpg
from opentelemetry import trace

from backend.monitoring.metrics import retrieval_latency
from backend.providers.client import NeuroFlowClient

from .fusion import reciprocal_rank_fusion
from .models import RetrievalResult
from .query_processor import ProcessedQuery

tracer = trace.get_tracer(__name__)


class Retriever:
    def __init__(self, db_pool: asyncpg.Pool, client: NeuroFlowClient) -> None:
        self.db_pool = db_pool
        self.client = client

    async def retrieve(
        self,
        processed_query: ProcessedQuery,
        k: int = 20,
        use_hyde: bool = False,
        pipeline_id: str | None = None,
        run_id: str | None = None,
        rrf_weights: list[float] | None = None,
        use_cache: bool = True,
        dense_k: int | None = None,
        sparse_k: int | None = None,
        rrf_k: int = 60,
    ) -> list[RetrievalResult]:
        # Run three strategies in parallel
        results = await asyncio.gather(
            self._dense_retrieval(
                processed_query, dense_k or k, use_hyde, pipeline_id, run_id, use_cache
            ),
            self._sparse_retrieval(processed_query, sparse_k or k, pipeline_id, run_id),
            self._metadata_retrieval(processed_query, k, pipeline_id, run_id, use_cache),
        )

        # Fuse results
        with tracer.start_as_current_span("retrieval.fusion") as span:
            if pipeline_id:
                span.set_attribute("pipeline_id", pipeline_id)
            if run_id:
                span.set_attribute("run_id", run_id)

            weights = rrf_weights if rrf_weights else [0.6, 0.4, 1.0]
            fused = reciprocal_rank_fusion(list(results), k=rrf_k, weights=weights)
            span.set_attribute("chunk_count", len(fused))
            return fused

    async def _dense_retrieval(
        self,
        processed_query: ProcessedQuery,
        k: int,
        use_hyde: bool,
        pipeline_id: str | None = None,
        run_id: str | None = None,
        use_cache: bool = True,
    ) -> list[RetrievalResult]:
        start_time = time.time()
        with tracer.start_as_current_span("retrieval.dense") as span:
            if pipeline_id:
                span.set_attribute("pipeline_id", pipeline_id)
            if run_id:
                span.set_attribute("run_id", run_id)
            if use_hyde and processed_query.hypothetical_document:
                queries = [processed_query.hypothetical_document] + processed_query.expanded_queries
            else:
                queries = [processed_query.original_query] + processed_query.expanded_queries

            # Embed all queries (original + expanded) in one shot
            embeddings = await self.client.embed(queries, use_cache=use_cache)

            results_list = []

            async with self.db_pool.acquire() as conn:
                for emb in embeddings:
                    rows = await conn.fetch(
                        """
                        SELECT id, document_id, content, metadata, embedding <=> $1::vector AS score
                        FROM chunks
                        ORDER BY embedding <=> $1::vector
                        LIMIT $2
                        """,
                        json.dumps(emb),
                        k,
                    )

                    for row in rows:
                        results_list.append(
                            RetrievalResult(
                                chunk_id=str(row["id"]),
                                document_id=str(row["document_id"]),
                                content=row["content"],
                                metadata=json.loads(row["metadata"])
                                if isinstance(row["metadata"], str)
                                else row["metadata"],
                                score=1.0
                                - float(row["score"]),  # convert distance to similarity roughly
                            )
                        )

            unique_results: dict[str, RetrievalResult] = {}
            for r in results_list:
                if r.chunk_id not in unique_results or r.score > unique_results[r.chunk_id].score:
                    unique_results[r.chunk_id] = r

            sorted_results = sorted(unique_results.values(), key=lambda x: x.score, reverse=True)[
                :k
            ]
            span.set_attribute("chunk_count", len(sorted_results))

            duration = time.time() - start_time
            retrieval_latency.labels(strategy="dense").observe(duration)

            return sorted_results

    async def _sparse_retrieval(
        self,
        processed_query: ProcessedQuery,
        k: int,
        pipeline_id: str | None = None,
        run_id: str | None = None,
    ) -> list[RetrievalResult]:
        start_time = time.time()
        with tracer.start_as_current_span("retrieval.sparse") as span:
            if pipeline_id:
                span.set_attribute("pipeline_id", pipeline_id)
            if run_id:
                span.set_attribute("run_id", run_id)
            queries = [processed_query.original_query] + processed_query.expanded_queries
            results_list = []

            async with self.db_pool.acquire() as conn:
                for q in queries:
                    rows = await conn.fetch(
                        """
                        SELECT id, document_id, content, metadata,
                               ts_rank_cd(to_tsvector('english', content), plainto_tsquery('english', $1)) AS score
                        FROM chunks
                        WHERE to_tsvector('english', content) @@ plainto_tsquery('english', $1)
                        ORDER BY score DESC
                        LIMIT $2
                        """,  # noqa: E501
                        q,
                        k,
                    )

                    for row in rows:
                        results_list.append(
                            RetrievalResult(
                                chunk_id=str(row["id"]),
                                document_id=str(row["document_id"]),
                                content=row["content"],
                                metadata=json.loads(row["metadata"])
                                if isinstance(row["metadata"], str)
                                else row["metadata"],
                                score=float(row["score"]),
                            )
                        )

            unique_results: dict[str, RetrievalResult] = {}
            for r in results_list:
                if r.chunk_id not in unique_results or r.score > unique_results[r.chunk_id].score:
                    unique_results[r.chunk_id] = r

            sorted_results = sorted(unique_results.values(), key=lambda x: x.score, reverse=True)[
                :k
            ]
            span.set_attribute("chunk_count", len(sorted_results))

            duration = time.time() - start_time
            retrieval_latency.labels(strategy="sparse").observe(duration)

            return sorted_results

    async def _metadata_retrieval(
        self,
        processed_query: ProcessedQuery,
        k: int,
        pipeline_id: str | None = None,
        run_id: str | None = None,
        use_cache: bool = True,
    ) -> list[RetrievalResult]:
        start_time = time.time()
        with tracer.start_as_current_span("retrieval.metadata") as span:
            if pipeline_id:
                span.set_attribute("pipeline_id", pipeline_id)
            if run_id:
                span.set_attribute("run_id", run_id)
            if not processed_query.metadata_filters:
                span.set_attribute("chunk_count", 0)
                return []

            embeddings = await self.client.embed(
                [processed_query.original_query], use_cache=use_cache
            )
            emb = embeddings[0]

            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, document_id, content, metadata, embedding <=> $2::vector AS distance
                    FROM chunks
                    WHERE metadata @> $1::jsonb
                    ORDER BY embedding <=> $2::vector
                    LIMIT $3
                    """,
                    json.dumps(processed_query.metadata_filters),
                    json.dumps(emb),
                    k,
                )

                results = [
                    RetrievalResult(
                        chunk_id=str(row["id"]),
                        document_id=str(row["document_id"]),
                        content=row["content"],
                        metadata=json.loads(row["metadata"])
                        if isinstance(row["metadata"], str)
                        else row["metadata"],
                        score=1.0 - float(row["distance"]),
                    )
                    for row in rows
                ]

                span.set_attribute("chunk_count", len(results))

                duration = time.time() - start_time
                retrieval_latency.labels(strategy="metadata").observe(duration)

                return results
