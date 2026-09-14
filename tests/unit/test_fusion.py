import sys
sys.path.insert(0, ".")
from pipelines.retrieval.fusion import reciprocal_rank_fusion
from pipelines.retrieval.types import RetrievalResult

def _r(chunk_id, score=0.0, method="dense"):
    return RetrievalResult(chunk_id=chunk_id, content=f"content-{chunk_id}", score=score, retrieval_method=method)

def test_rrf_formula_exact_for_single_list():
    results = reciprocal_rank_fusion([[_r("A"), _r("B")]], k=60)
    assert abs(results[0].score - 1 / 61) < 1e-9
    assert abs(results[1].score - 1 / 62) < 1e-9

def test_rrf_boosts_chunks_in_multiple_lists():
    dense = [_r("A"), _r("B"), _r("C")]
    sparse = [_r("D"), _r("A")]
    fused = reciprocal_rank_fusion([dense, sparse], k=60)
    a = next(r for r in fused if r.chunk_id == "A")
    c = next(r for r in fused if r.chunk_id == "C")
    assert a.score > c.score

def test_rrf_sorts_descending():
    fused = reciprocal_rank_fusion([[_r("A"), _r("B"), _r("C")]], k=60)
    scores = [r.score for r in fused]
    assert scores == sorted(scores, reverse=True)

def test_rrf_empty_lists_returns_empty():
    assert reciprocal_rank_fusion([[], []], k=60) == []

def test_rrf_result_method_tags_contributing_strategies():
    fused = reciprocal_rank_fusion([[_r("A", method="dense")], [_r("A", method="sparse")]], k=60)
    assert "dense" in fused[0].retrieval_method
    assert "sparse" in fused[0].retrieval_method

def test_rrf_deduplicates_by_chunk_id():
    fused = reciprocal_rank_fusion([[_r("A"), _r("A")]], k=60)
    assert [r.chunk_id for r in fused].count("A") == 1

def test_weighted_rrf_favors_higher_weighted_list():
    dense = [_r("A")]
    sparse = [_r("B")]
    fused = reciprocal_rank_fusion([dense, sparse], k=60, weights=[2.0, 1.0])
    scores = {r.chunk_id: r.score for r in fused}
    assert scores["A"] > scores["B"]
