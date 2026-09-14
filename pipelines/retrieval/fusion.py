"""
Reciprocal Rank Fusion: merges N ranked result lists into one, boosting
chunks that appear across multiple lists — the core mechanism that makes
hybrid (dense + sparse + metadata) retrieval outperform any single method.
"""
from dataclasses import replace

from pipelines.retrieval.types import RetrievalResult
from opentelemetry import trace

_tracer = trace.get_tracer("neuroflow.retrieval")

DEFAULT_RRF_K = 60


def reciprocal_rank_fusion(
    result_lists: list[list[RetrievalResult]],
    k: int = DEFAULT_RRF_K,
) -> list[RetrievalResult]:
    """score(chunk) = sum over lists containing it of 1 / (k + rank),
    rank is 1-indexed position within that list. A chunk in lists at
    rank 1 and rank 1 scores 2/(k+1); a chunk in only one list at rank 1
    scores 1/(k+1) — appearing in more lists strictly increases the score
    at any fixed rank, which is the "boost" the task spec calls for.
    """
    with _tracer.start_as_current_span("retrieval.fusion") as span:
        span.set_attribute("input_list_count", len(result_lists))
        span.set_attribute("input_chunk_count", sum(len(l) for l in result_lists))
        result = _reciprocal_rank_fusion_inner(result_lists, k)
        span.set_attribute("fused_chunk_count", len(result))
        return result


def _reciprocal_rank_fusion_inner(result_lists: list[list[RetrievalResult]], k: int) -> list[RetrievalResult]:
    fused_scores: dict[str, float] = {}
    representative: dict[str, RetrievalResult] = {}
    matched_methods: dict[str, set[str]] = {}

    for result_list in result_lists:
        for rank, result in enumerate(result_list, start=1):
            fused_scores[result.chunk_id] = fused_scores.get(result.chunk_id, 0.0) + 1.0 / (k + rank)
            matched_methods.setdefault(result.chunk_id, set()).add(result.retrieval_method or "unknown")
            # Keep the first-seen result as the representative for
            # content/metadata — all lists should carry the same content
            # for a given chunk_id, so this is just picking any one of them.
            representative.setdefault(result.chunk_id, result)

    fused: list[RetrievalResult] = []
    for chunk_id, score in fused_scores.items():
        base = representative[chunk_id]
        fused.append(
            replace(
                base,
                score=score,
                retrieval_method="rrf(" + "+".join(sorted(matched_methods[chunk_id])) + ")",
            )
        )

    fused.sort(key=lambda r: r.score, reverse=True)
    return fused
