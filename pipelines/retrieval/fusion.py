from .models import RetrievalResult


def reciprocal_rank_fusion(
    result_lists: list[list[RetrievalResult]], k: int = 60, weights: list[float] | None = None
) -> list[RetrievalResult]:
    """
    Combines multiple retrieval lists using Reciprocal Rank Fusion.
    For each chunk, score = sum(weight * 1 / (k + rank)) across all lists.
    """
    chunk_scores: dict[str, float] = {}
    chunk_map: dict[str, RetrievalResult] = {}

    for i, result_list in enumerate(result_lists):
        weight = weights[i] if weights and i < len(weights) else 1.0
        for rank, result in enumerate(result_list):
            chunk_id = result.chunk_id

            # Map chunk for later retrieval
            if chunk_id not in chunk_map:
                chunk_map[chunk_id] = result
                chunk_scores[chunk_id] = 0.0

            # Compute RRF score contribution
            score_contribution = (1.0 / (k + (rank + 1))) * weight
            chunk_scores[chunk_id] += score_contribution

    # Create new results with fused scores
    fused_results = []
    for chunk_id, score in chunk_scores.items():
        original = chunk_map[chunk_id]
        # Create a copy with the new score
        fused = RetrievalResult(
            chunk_id=original.chunk_id,
            document_id=original.document_id,
            content=original.content,
            metadata=original.metadata,
            score=score,
        )
        fused_results.append(fused)

    # Sort descending by score
    fused_results.sort(key=lambda x: x.score, reverse=True)
    return fused_results
