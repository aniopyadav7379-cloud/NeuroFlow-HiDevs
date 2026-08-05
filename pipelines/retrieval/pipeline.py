"""
RetrievalPipeline: the full 5-step flow from docs/architecture.md §2 —
query processing -> parallel hybrid retrieval -> RRF fusion (inside
Retriever.retrieve) -> cross-encoder rerank -> context window assembly.

This is what the Generation Subsystem (Task 36+) calls; nothing downstream
should re-implement any of these steps.
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

DEFAULT_RETRIEVAL_K = 20
DEFAULT_RERANK_CANDIDATES = 40
DEFAULT_FINAL_K = 8


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
        self.reranker_scorer = reranker_scorer or APIRerankerScorer(llm_client)

    async def retrieve(
        self,
        query: str,
        *,
        k: int = DEFAULT_RETRIEVAL_K,
        rerank_candidates: int = DEFAULT_RERANK_CANDIDATES,
        final_k: int = DEFAULT_FINAL_K,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        use_hyde: bool = False,
    ) -> RetrievalPipelineResult:
        processed = await process_query(query, self.llm_client)

        rrf_chunks = await self.retriever.retrieve(query, k=k, processed=processed, use_hyde=use_hyde)

        reranked = await rerank(
            query, rrf_chunks[:rerank_candidates], self.reranker_scorer, top_k=final_k
        )

        assembled = assemble_context(reranked, token_budget=token_budget)

        return RetrievalPipelineResult(
            assembled=assembled,
            processed_query=processed,
            reranked_chunks=reranked,
            rrf_chunks=rrf_chunks,
        )
