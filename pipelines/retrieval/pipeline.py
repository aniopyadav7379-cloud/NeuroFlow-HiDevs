"""
RetrievalPipeline: the full 5-step flow from docs/architecture.md §2 —
query processing -> parallel hybrid retrieval -> RRF fusion (inside
Retriever.retrieve) -> cross-encoder rerank -> context window assembly.

This is what the Generation Subsystem calls; nothing downstream should
re-implement any of these steps. Task 8 threads a pipeline's
retrieval.* config through here (dense_k/sparse_k/top_k_after_rerank/
reranker/query_expansion) via the `**overrides`-style explicit kwargs
below, so a pipeline's stored config actually changes retrieval
behavior, not just documents an intent.
"""
import logging
from dataclasses import dataclass

import asyncpg

from backend.providers.client import NeuroFlowClient
from pipelines.retrieval.context_assembler import DEFAULT_TOKEN_BUDGET, AssembledContext, assemble_context
from pipelines.retrieval.query_processor import ProcessedQuery, process_query
from pipelines.retrieval.reranker import APIRerankerScorer, rerank
from pipelines.retrieval.retriever import Retriever
from pipelines.retrieval.types import RetrievalResult

logger = logging.getLogger("neuroflow.retrieval.pipeline")

from opentelemetry import trace
_tracer = trace.get_tracer("neuroflow.retrieval")

DEFAULT_RETRIEVAL_K = 20
DEFAULT_RERANK_CANDIDATES = 40
DEFAULT_FINAL_K = 8

RERANKER_NONE = "none"
RERANKER_CROSS_ENCODER = "cross-encoder"
RERANKER_LOCAL_CROSS_ENCODER = "local-cross-encoder"


@dataclass
class RetrievalPipelineResult:
    assembled: AssembledContext
    processed_query: ProcessedQuery
    reranked_chunks: list[RetrievalResult]
    rrf_chunks: list[RetrievalResult]  # kept for evaluation (RRF-only vs reranked comparison)


class RetrievalPipeline:
    def __init__(self, pool: asyncpg.Pool, llm_client: NeuroFlowClient, reranker_scorer=None):
        self.pool = pool
        self.llm_client = llm_client
        self.retriever = Retriever(pool, llm_client)
        self._default_reranker_scorer = reranker_scorer or APIRerankerScorer(llm_client)

    def _resolve_reranker_scorer(self, reranker: str):
        if reranker == RERANKER_NONE:
            return None
        if reranker == RERANKER_LOCAL_CROSS_ENCODER:
            from pipelines.retrieval.reranker import LocalCrossEncoderScorer
            return LocalCrossEncoderScorer()
        return self._default_reranker_scorer  # "cross-encoder" (API-based) is the default

    async def retrieve(
        self,
        query: str,
        *,
        k: int = DEFAULT_RETRIEVAL_K,
        dense_k: int | None = None,
        sparse_k: int | None = None,
        rerank_candidates: int = DEFAULT_RERANK_CANDIDATES,
        final_k: int = DEFAULT_FINAL_K,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        use_hyde: bool = False,
        enable_query_expansion: bool = True,
        reranker: str = RERANKER_CROSS_ENCODER,
    ) -> RetrievalPipelineResult:
        with _tracer.start_as_current_span("retrieval.pipeline") as span:
            span.set_attribute("query_length", len(query))
            span.set_attribute("reranker", reranker)

            processed = await process_query(query, self.llm_client, enable_expansion=enable_query_expansion)

            rrf_chunks = await self.retriever.retrieve(
                query, k=k, dense_k=dense_k, sparse_k=sparse_k,
                processed=processed, use_hyde=use_hyde, enable_query_expansion=enable_query_expansion,
            )

            scorer = self._resolve_reranker_scorer(reranker)
            if scorer is None:
                # reranker="none": trust RRF order as-is, just truncate to final_k.
                reranked = rrf_chunks[:final_k]
            else:
                reranked = await rerank(query, rrf_chunks[:rerank_candidates], scorer, top_k=final_k)

            assembled = assemble_context(reranked, token_budget=token_budget)

            span.set_attribute("rrf_chunk_count", len(rrf_chunks))
            span.set_attribute("final_chunk_count", len(assembled.chunks_used))

            return RetrievalPipelineResult(
                assembled=assembled,
                processed_query=processed,
                reranked_chunks=reranked,
                rrf_chunks=rrf_chunks,
            )
