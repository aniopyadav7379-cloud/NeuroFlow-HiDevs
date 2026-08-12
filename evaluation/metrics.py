"""
Pure retrieval-quality metric functions, kept separate from
retrieval_eval.py's DB/LLM plumbing so they're trivially unit-testable
with synthetic data (see the smoke test referenced in the task summary).
"""


def hit_rate(results: list, relevant_ids: set[str]) -> bool:
    """True if ANY returned result is in the known-relevant set."""
    return any(r.chunk_id in relevant_ids for r in results)


def reciprocal_rank(results: list, relevant_ids: set[str]) -> float:
    """1/rank of the first relevant result found (1-indexed), 0.0 if none
    of the returned results are relevant."""
    for i, r in enumerate(results, start=1):
        if r.chunk_id in relevant_ids:
            return 1.0 / i
    return 0.0


def aggregate(per_query_hits: list[bool], per_query_rr: list[float]) -> dict:
    n = len(per_query_hits)
    if n == 0:
        return {"hit_rate": 0.0, "mrr": 0.0, "n": 0}
    return {
        "hit_rate": sum(per_query_hits) / n,
        "mrr": sum(per_query_rr) / n,
        "n": n,
    }
