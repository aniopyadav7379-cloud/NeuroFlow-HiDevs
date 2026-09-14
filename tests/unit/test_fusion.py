from pipelines.retrieval.models import RetrievalResult
from pipelines.retrieval.fusion import reciprocal_rank_fusion

def test_rrf_empty():
    results = reciprocal_rank_fusion([])
    assert len(results) == 0

def test_rrf_single_list():
    res1 = RetrievalResult(chunk_id="c1", document_id="d1", content="t1", metadata={}, score=0.9)
    res2 = RetrievalResult(chunk_id="c2", document_id="d1", content="t2", metadata={}, score=0.8)
    
    fused = reciprocal_rank_fusion([[res1, res2]], k=60)
    assert len(fused) == 2
    assert fused[0].chunk_id == "c1"
    assert fused[1].chunk_id == "c2"
    # c1 is rank 0 -> 1/(60+1)
    assert fused[0].score == 1.0 / 61.0
    # c2 is rank 1 -> 1/(60+2)
    assert fused[1].score == 1.0 / 62.0

def test_rrf_multiple_lists_overlapping():
    res1_list1 = RetrievalResult(chunk_id="c1", document_id="d1", content="t1", metadata={}, score=0.9)
    res2_list1 = RetrievalResult(chunk_id="c2", document_id="d1", content="t2", metadata={}, score=0.8)
    
    res2_list2 = RetrievalResult(chunk_id="c2", document_id="d1", content="t2", metadata={}, score=0.85)
    res3_list2 = RetrievalResult(chunk_id="c3", document_id="d1", content="t3", metadata={}, score=0.7)

    fused = reciprocal_rank_fusion([
        [res1_list1, res2_list1],
        [res2_list2, res3_list2]
    ], k=60)

    # fused should have c1, c2, c3
    assert len(fused) == 3
    
    # c1 score: 1/61
    # c2 score: 1/62 (from list 1) + 1/61 (from list 2) = 0.0325
    # c3 score: 1/62 (from list 2) = 0.0161
    # Therefore c2 should be rank 1!
    assert fused[0].chunk_id == "c2"
    assert fused[1].chunk_id == "c1"
    assert fused[2].chunk_id == "c3"

def test_rrf_custom_k():
    res1 = RetrievalResult(chunk_id="c1", document_id="d1", content="t1", metadata={}, score=0.9)
    fused = reciprocal_rank_fusion([[res1]], k=1)
    assert len(fused) == 1
    # score = 1/(1+1) = 0.5
    assert fused[0].score == 0.5

def test_rrf_order_preserved():
    res_a = RetrievalResult(chunk_id="A", document_id="d1", content="", metadata={}, score=0.9)
    res_b = RetrievalResult(chunk_id="B", document_id="d1", content="", metadata={}, score=0.8)
    res_c = RetrievalResult(chunk_id="C", document_id="d1", content="", metadata={}, score=0.7)
    
    fused = reciprocal_rank_fusion([[res_c, res_a, res_b]])
    assert fused[0].chunk_id == "C"
    assert fused[1].chunk_id == "A"
    assert fused[2].chunk_id == "B"
