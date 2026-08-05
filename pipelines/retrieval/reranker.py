"""
Cross-encoder reranking: scores (query, chunk) pairs jointly, unlike the
bi-encoder similarity used in dense retrieval where query and chunk are
embedded independently. Runs on the top-40 RRF-fused candidates.

Two implementations, per the task spec ("implement at least one, the API-
based approach is required, the local model is an optional optimization"):
  - APIRerankerScorer: LLM-based 0-10 scoring, parallel via asyncio.gather
  - LocalCrossEncoderScorer: sentence-transformers cross-encoder, optional
    (import is lazy — this module works without sentence-transformers
    installed as long as only the API scorer is used)
"""
import asyncio
import logging
import re

from backend.providers.base import ChatMessage
from backend.providers.client import NeuroFlowClient
from backend.providers.router import RoutingCriteria
from pipelines.retrieval.types import RetrievalResult

logger = logging.getLogger("neuroflow.retrieval.reranker")

RERANK_PROMPT = (
    "Rate the relevance of this passage to the query on a scale of 0-10. "
    "Query: {query}. Passage: {passage}. Return only the number."
)

_NUMBER_RE = re.compile(r"-?\d+(\.\d+)?")

DEFAULT_RERANK_MAX_COST_PER_CALL = 0.0005  # small scoring calls, tight cap


def _parse_score(text: str) -> float:
    match = _NUMBER_RE.search(text)
    if not match:
        logger.warning("could not parse a numeric score from reranker output %r, defaulting to 0", text)
        return 0.0
    value = float(match.group(0))
    return max(0.0, min(10.0, value))  # clamp to the requested 0-10 range


class APIRerankerScorer:
    """LLM-based cross-encoder substitute: one chat call per (query, chunk)
    pair, all pairs scored concurrently."""

    def __init__(self, client: NeuroFlowClient):
        self.client = client

    async def _score_one(self, query: str, chunk: RetrievalResult) -> float:
        try:
            result = await self.client.chat(
                [ChatMessage(role="user", content=RERANK_PROMPT.format(query=query, passage=chunk.content))],
                RoutingCriteria(task_type="reranking", max_cost_per_call=DEFAULT_RERANK_MAX_COST_PER_CALL),
            )
            return _parse_score(result.content)
        except Exception:
            logger.exception("reranking call failed for chunk_id=%s, scoring as 0", chunk.chunk_id)
            return 0.0

    async def score(self, query: str, candidates: list[RetrievalResult]) -> list[float]:
        return list(await asyncio.gather(*(self._score_one(query, c) for c in candidates)))


class LocalCrossEncoderScorer:
    """Optional optimization: sentence-transformers cross-encoder, run
    locally (no API cost, no network round-trip per pair, needs a model
    download + CPU/GPU inference instead). Import of sentence_transformers
    is deferred to __init__ so this class only requires the dependency
    when actually instantiated."""

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        from sentence_transformers import CrossEncoder  # local import — optional dependency

        self._model = CrossEncoder(model_name)

    async def score(self, query: str, candidates: list[RetrievalResult]) -> list[float]:
        pairs = [(query, c.content) for c in candidates]
        # CrossEncoder.predict is sync/CPU-bound — run off the event loop
        # so it doesn't block other coroutines (arq worker concurrency,
        # other in-flight requests in the API process, etc).
        raw_scores = await asyncio.to_thread(self._model.predict, pairs)
        return [float(s) for s in raw_scores]


async def rerank(
    query: str,
    candidates: list[RetrievalResult],
    scorer: APIRerankerScorer | LocalCrossEncoderScorer,
    top_k: int | None = None,
) -> list[RetrievalResult]:
    """Scores every candidate and returns them sorted by reranked score
    (descending), replacing `.score` with the cross-encoder score and
    `.retrieval_method` tagged so downstream code (context assembly,
    evaluation) can tell an RRF-only score from a reranked one."""
    if not candidates:
        return []

    scores = await scorer.score(query, candidates)
    reranked = []
    for candidate, score in zip(candidates, scores):
        reranked.append(
            RetrievalResult(
                chunk_id=candidate.chunk_id,
                content=candidate.content,
                score=score,
                metadata=candidate.metadata,
                document_id=candidate.document_id,
                retrieval_method=f"reranked({candidate.retrieval_method})",
            )
        )
    reranked.sort(key=lambda r: r.score, reverse=True)
    return reranked[:top_k] if top_k else reranked
